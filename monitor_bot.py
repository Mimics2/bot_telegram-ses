import os
import logging
import psycopg2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_connection():
    database_url = os.getenv('DATABASE_URL')
    return psycopg2.connect(database_url, sslmode='require')

def init_monitor_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS monitor_filters (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            session_string TEXT,
            filter_type TEXT,
            filter_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

class MonitorBot:
    def __init__(self, token: str):
        self.token = token
        self.app = Application.builder().token(token).build()
        self.active_clients = {}
        self.setup_handlers()
        init_monitor_db()

    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("addmonitor", self.add_monitor))
        self.app.add_handler(CommandHandler("stopmonitor", self.stop_monitor))
        self.app.add_handler(CommandHandler("mymonitors", self.my_monitors))
        self.app.add_handler(CommandHandler("addfilter", self.add_filter))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        welcome_text = """
👁️ **Бот мониторинга Telegram**

📋 Команды:
/addmonitor - Добавить сессию для мониторинга
/stopmonitor - Остановить мониторинг  
/mymonitors - Активные мониторинги
/addfilter - Добавить фильтр

Отправь /addmonitor с session string для начала!
        """
        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def add_monitor(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🔐 **Добавление мониторинга**\n\n"
            "Отправь session string:\n"
            "(полученный от бота сессий)"
        )
        context.user_data['awaiting_session'] = True

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if context.user_data.get('awaiting_session'):
            await self.process_new_session(update, context, update.message.text)
        elif context.user_data.get('awaiting_filter'):
            await self.process_new_filter(update, context, update.message.text)

    async def process_new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE, session_string: str):
        user_id = update.effective_user.id
        
        try:
            # Пытаемся подключиться с сессией
            client = TelegramClient(StringSession(), 6, "eb06d4abfb49dc3eeb1aeb98ae0f581e")
            await client.start()
            
            me = await client.get_me()
            if not me:
                await update.message.reply_text("❌ Неверная сессия")
                await client.disconnect()
                return
            
            # Сохраняем клиент
            key = f"{user_id}_{session_string}"
            self.active_clients[key] = client
            
            # Настраиваем обработчик
            @client.on(events.NewMessage)
            async def handler(event):
                if event.is_private:
                    await self.process_monitored_message(user_id, event.message, session_string)
            
            await update.message.reply_text(
                f"✅ **Мониторинг запущен!**\n\n"
                f"📱 Аккаунт: {me.phone}\n"
                f"👤 Имя: {me.first_name or 'N/A'}\n\n"
                f"Теперь настрой фильтры: /addfilter"
            )
            
            context.user_data.pop('awaiting_session', None)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def process_monitored_message(self, user_id: int, message, session_string: str):
        """Обрабатывает сообщение и применяет фильтры"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT filter_type, filter_value FROM monitor_filters WHERE user_id = %s AND session_string = %s',
                (user_id, session_string)
            )
            filters_list = cursor.fetchall()
            conn.close()
            
            message_text = message.text or ""
            sender = await message.get_sender()
            sender_name = getattr(sender, 'first_name', 'Unknown') or 'Unknown'
            sender_phone = getattr(sender, 'phone', 'Unknown')
            
            # Если фильтров нет - пересылаем все
            if not filters_list:
                await self.forward_message(user_id, message, sender_name, sender_phone, "Без фильтра")
                return
            
            # Проверяем фильтры
            for filter_type, filter_value in filters_list:
                if filter_type == "keyword" and filter_value.lower() in message_text.lower():
                    await self.forward_message(user_id, message, sender_name, sender_phone, f"Ключ: {filter_value}")
                    break
                elif filter_type == "regex" and re.search(filter_value, message_text, re.IGNORECASE):
                    await self.forward_message(user_id, message, sender_name, sender_phone, f"Regex: {filter_value}")
                    break
                elif filter_type == "all":
                    await self.forward_message(user_id, message, sender_name, sender_phone, "Все сообщения")
                    break
                    
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def forward_message(self, user_id: int, message, sender_name: str, sender_phone: str, filter_info: str):
        """Пересылает сообщение пользователю"""
        try:
            text = f"📨 **Новое сообщение**\n\n"
            text += f"👤 От: {sender_name}\n"
            text += f"📱 Номер: {sender_phone}\n"
            text += f"🔍 Фильтр: {filter_info}\n"
            text += f"💬 Текст: {message.text}\n"
            
            await self.app.bot.send_message(user_id, text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error forwarding: {e}")

    async def add_filter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Получаем активные сессии пользователя
        user_sessions = [k for k in self.active_clients.keys() if k.startswith(str(user_id))]
        
        if not user_sessions:
            await update.message.reply_text("❌ Нет активных мониторингов. Сначала добавь сессию.")
            return
        
        response = "🔍 **Добавление фильтра**\n\nВыбери тип:\n\n"
        response += "1. **keyword** - по ключевому слову\n"
        response += "2. **regex** - по регулярному выражению\n"
        response += "3. **all** - все сообщения\n\n"
        response += "Ответь в формате: `тип_фильтра значение`\n"
        response += "Пример: `keyword привет`"
        
        await update.message.reply_text(response, parse_mode='Markdown')
        context.user_data['awaiting_filter'] = True

    async def process_new_filter(self, update: Update, context: ContextTypes.DEFAULT_TYPE, filter_text: str):
        user_id = update.effective_user.id
        
        try:
            parts = filter_text.split(' ', 1)
            if len(parts) < 2:
                await update.message.reply_text("❌ Неверный формат. Используй: `тип значение`")
                return
            
            filter_type, filter_value = parts[0].lower(), parts[1]
            
            if filter_type not in ['keyword', 'regex', 'all']:
                await update.message.reply_text("❌ Неверный тип. Доступно: keyword, regex, all")
                return
            
            # Сохраняем фильтр для всех активных сессий
            user_sessions = [k for k in self.active_clients.keys() if k.startswith(str(user_id))]
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            for session_key in user_sessions:
                session_string = session_key.split('_', 1)[1]
                cursor.execute(
                    'INSERT INTO monitor_filters (user_id, session_string, filter_type, filter_value) VALUES (%s, %s, %s, %s)',
                    (user_id, session_string, filter_type, filter_value)
                )
            
            conn.commit()
            conn.close()
            
            await update.message.reply_text(f"✅ Фильтр добавлен: {filter_type} - {filter_value}")
            context.user_data.pop('awaiting_filter', None)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def my_monitors(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_sessions = [k for k in self.active_clients.keys() if k.startswith(str(user_id))]
        
        if not user_sessions:
            await update.message.reply_text("❌ Нет активных мониторингов")
            return
        
        response = "👁️ **Активные мониторинги:**\n\n"
        for i, session_key in enumerate(user_sessions, 1):
            client = self.active_clients[session_key]
            me = await client.get_me()
            response += f"{i}. {me.phone} - {me.first_name or 'N/A'}\n"
        
        await update.message.reply_text(response)

    async def stop_monitor(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_sessions = [k for k in self.active_clients.keys() if k.startswith(str(user_id))]
        
        if not user_sessions:
            await update.message.reply_text("❌ Нет активных мониторингов")
            return
        
        stopped_count = 0
        for session_key in user_sessions:
            client = self.active_clients[session_key]
            await client.disconnect()
            del self.active_clients[session_key]
            stopped_count += 1
        
        await update.message.reply_text(f"✅ Остановлено {stopped_count} мониторингов")

    def run(self):
        self.app.run_polling(drop_pending_updates=True)
