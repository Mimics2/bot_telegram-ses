import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient
from telethon.sessions import StringSession
import sqlite3
import json

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            user_id INTEGER,
            phone TEXT,
            session_string TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, phone)
        )
    ''')
    conn.commit()
    conn.close()

class SessionBot:
    def __init__(self, token: str):
        self.token = token
        self.app = Application.builder().token(token).build()
        self.setup_handlers()
        init_db()

    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("newsession", self.new_session))
        self.app.add_handler(CommandHandler("mysessions", self.my_sessions))
        self.app.add_handler(CommandHandler("delsession", self.del_session))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        welcome_text = """
🔐 **Бот для создания Telegram сессий**

📋 Доступные команды:
/newsession - Создать новую сессию
/mysessions - Мои сессии
/delsession - Удалить сессию

Просто нажмите /newsession и следуйте инструкциям!
        """
        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Проверяем количество активных сессий
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        session_count = cursor.execute(
            'SELECT COUNT(*) FROM sessions WHERE user_id = ?', (user_id,)
        ).fetchone()[0]
        conn.close()
        
        if session_count >= 5:  # Лимит сессий на пользователя
            await update.message.reply_text("❌ Вы можете иметь не более 5 активных сессий")
            return
        
        await update.message.reply_text(
            "📱 **Создание новой сессии**\n\n"
            "Введите номер телефона в международном формате:\n"
            "Пример: +77777777777\n\n"
            "⚠️ Убедитесь, что у вас есть доступ к этому номеру для получения кода подтверждения!"
        )
        context.user_data['state'] = 'awaiting_phone'

    async def my_sessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        sessions = cursor.execute(
            'SELECT phone, session_string FROM sessions WHERE user_id = ?', (user_id,)
        ).fetchall()
        conn.close()
        
        if not sessions:
            await update.message.reply_text("❌ У вас нет активных сессий")
            return
        
        response = "📋 **Ваши активные сессии:**\n\n"
        for i, (phone, session_str) in enumerate(sessions, 1):
            response += f"{i}. **Номер:** `{phone}`\n"
            response += f"   **Сессия:** `{session_str[:50]}...`\n\n"
        
        await update.message.reply_text(response, parse_mode='Markdown')

    async def del_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        sessions = cursor.execute(
            'SELECT phone FROM sessions WHERE user_id = ?', (user_id,)
        ).fetchall()
        conn.close()
        
        if not sessions:
            await update.message.reply_text("❌ У вас нет активных сессий для удаления")
            return
        
        response = "🗑️ **Выберите сессию для удаления:**\n\n"
        for i, (phone,) in enumerate(sessions, 1):
            response += f"{i}. {phone}\n"
        
        response += "\nОтветьте номером сессии для удаления"
        await update.message.reply_text(response)
        context.user_data['state'] = 'awaiting_delete'
        context.user_data['sessions_list'] = [phone for phone, in sessions]

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text
        
        state = context.user_data.get('state')
        
        if state == 'awaiting_phone':
            await self.process_phone(update, context, text)
        elif state == 'awaiting_code':
            await self.process_code(update, context, text)
        elif state == 'awaiting_password':
            await self.process_password(update, context, text)
        elif state == 'awaiting_delete':
            await self.process_delete(update, context, text)

    async def process_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE, phone: str):
        # Проверяем формат номера
        if not phone.startswith('+') or not phone[1:].isdigit():
            await update.message.reply_text("❌ Неверный формат номера. Используйте международный формат: +77777777777")
            return
        
        # Сохраняем номер и создаем клиент
        context.user_data['phone'] = phone
        
        try:
            # Создаем клиент с рандомными API данными (они не важны для сессии)
            client = TelegramClient(StringSession(), 1, "b")
            await client.connect()
            
            # Отправляем запрос кода
            sent_code = await client.send_code_request(phone)
            context.user_data['phone_code_hash'] = sent_code.phone_code_hash
            context.user_data['client'] = client
            
            await update.message.reply_text(
                "✅ Код подтверждения отправлен!\n\n"
                "📨 Введите код из Telegram:\n"
                "(5-6 цифр)"
            )
            context.user_data['state'] = 'awaiting_code'
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            if 'client' in context.user_data:
                await context.user_data['client'].disconnect()

    async def process_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
        if not code.isdigit():
            await update.message.reply_text("❌ Код должен содержать только цифры")
            return
        
        client = context.user_data.get('client')
        phone = context.user_data.get('phone')
        phone_code_hash = context.user_data.get('phone_code_hash')
        
        try:
            # Пытаемся войти с кодом
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            
            # Успешная авторизация
            session_string = client.session.save()
            
            # Сохраняем в базу
            conn = sqlite3.connect('sessions.db')
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO sessions (user_id, phone, session_string) VALUES (?, ?, ?)',
                (update.effective_user.id, phone, session_string)
            )
            conn.commit()
            conn.close()
            
            await update.message.reply_text(
                f"✅ **Сессия успешно создана!**\n\n"
                f"📱 Номер: `{phone}`\n"
                f"🔐 Сессия: `{session_string}`\n\n"
                f"Сохраните эту строку для использования в боте мониторинга!",
                parse_mode='Markdown'
            )
            
            await client.disconnect()
            
            # Очищаем данные
            for key in ['state', 'phone', 'client', 'phone_code_hash']:
                context.user_data.pop(key, None)
                
        except Exception as e:
            error_msg = str(e)
            if "two-steps" in error_msg.lower():
                await update.message.reply_text(
                    "🔒 Включена двухфакторная аутентификация.\n"
                    "Введите пароль:"
                )
                context.user_data['state'] = 'awaiting_password'
            else:
                await update.message.reply_text(f"❌ Ошибка: {error_msg}")
                await client.disconnect()

    async def process_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE, password: str):
        client = context.user_data.get('client')
        phone = context.user_data.get('phone')
        
        try:
            await client.sign_in(password=password)
            
            # Успешная авторизация с паролем
            session_string = client.session.save()
            
            # Сохраняем в базу
            conn = sqlite3.connect('sessions.db')
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO sessions (user_id, phone, session_string) VALUES (?, ?, ?)',
                (update.effective_user.id, phone, session_string)
            )
            conn.commit()
            conn.close()
            
            await update.message.reply_text(
                f"✅ **Сессия успешно создана!**\n\n"
                f"📱 Номер: `{phone}`\n"
                f"🔐 Сессия: `{session_string}`\n\n"
                f"Сохраните эту строку для использования в боте мониторинга!",
                parse_mode='Markdown'
            )
            
            await client.disconnect()
            
            # Очищаем данные
            for key in ['state', 'phone', 'client', 'phone_code_hash']:
                context.user_data.pop(key, None)
                
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            await client.disconnect()

    async def process_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE, choice: str):
        if not choice.isdigit():
            await update.message.reply_text("❌ Введите номер сессии")
            return
        
        index = int(choice) - 1
        sessions_list = context.user_data.get('sessions_list', [])
        
        if index < 0 or index >= len(sessions_list):
            await update.message.reply_text("❌ Неверный номер сессии")
            return
        
        phone_to_delete = sessions_list[index]
        
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        cursor.execute(
            'DELETE FROM sessions WHERE user_id = ? AND phone = ?',
            (update.effective_user.id, phone_to_delete)
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Сессия для {phone_to_delete} удалена")
        
        # Очищаем данные
        for key in ['state', 'sessions_list']:
            context.user_data.pop(key, None)

    def run(self):
        self.app.run_polling()

if __name__ == "__main__":
    # Токен бота от @BotFather
    BOT_TOKEN = "8307838767:AAFTlaYRF12rPfitbVwDM0tsuZ4HApVykmE"
    
    bot = SessionBot(BOT_TOKEN)
    print("Бот создания сессий запущен...")
    bot.run()
