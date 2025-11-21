import os
import logging
import psycopg2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient
from telethon.sessions import StringSession
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_connection():
    """Получаем соединение с PostgreSQL"""
    database_url = os.getenv('DATABASE_URL')
    return psycopg2.connect(database_url, sslmode='require')

def init_db():
    """Инициализация таблиц в PostgreSQL"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            phone TEXT,
            session_string TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_phone 
        ON sessions (user_id, phone)
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
        welcome_text = """
🔐 **Бот для создания Telegram сессий**

📋 Команды:
/newsession - Создать новую сессию
/mysessions - Мои сессии  
/delsession - Удалить сессию

Просто нажми /newsession и следуй инструкциям!
        """
        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM sessions WHERE user_id = %s', (user_id,))
        session_count = cursor.fetchone()[0]
        conn.close()
        
        if session_count >= 3:
            await update.message.reply_text("❌ Максимум 3 сессии на пользователя")
            return
        
        await update.message.reply_text(
            "📱 **Создание новой сессии**\n\n"
            "Введите номер телефона в международном формате:\n"
            "Пример: +77777777777\n\n"
            "⚠️ Убедись, что у тебя есть доступ к этому номеру для получения кода!"
        )
        context.user_data['state'] = 'awaiting_phone'

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        if not phone.startswith('+') or not phone[1:].isdigit():
            await update.message.reply_text("❌ Неверный формат. Используй: +77777777777")
            return
        
        context.user_data['phone'] = phone
        
        try:
            # Используем универсальные API данные
            client = TelegramClient(StringSession(), 2040, "b18441a1ff607e10a989891a5462e627")
            await client.connect()
            
            sent_code = await client.send_code_request(phone)
            context.user_data['phone_code_hash'] = sent_code.phone_code_hash
            context.user_data['client'] = client
            
            await update.message.reply_text(
                "✅ Код отправлен!\n\n"
                "📨 Введите код из Telegram:"
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
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            await self.save_session(update, context, client, phone)
            
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
            await self.save_session(update, context, client, phone)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            await client.disconnect()

    async def save_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE, client, phone: str):
        """Сохраняет сессию в базу и отправляет пользователю"""
        session_string = client.session.save()
        user_id = update.effective_user.id
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO sessions (user_id, phone, session_string) VALUES (%s, %s, %s)',
            (user_id, phone, session_string)
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ **Сессия создана!**\n\n"
            f"📱 Номер: `{phone}`\n"
            f"🔐 Сессия: `{session_string}`\n\n"
            f"Используй эту строку в боте мониторинга!",
            parse_mode='Markdown'
        )
        
        await client.disconnect()
        # Очищаем контекст
        for key in ['state', 'phone', 'client', 'phone_code_hash']:
            context.user_data.pop(key, None)

    async def my_sessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT phone, session_string FROM sessions WHERE user_id = %s', (user_id,)
        )
        sessions = cursor.fetchall()
        conn.close()
        
        if not sessions:
            await update.message.reply_text("❌ У тебя нет сессий")
            return
        
        response = "📋 **Твои сессии:**\n\n"
        for i, (phone, session_str) in enumerate(sessions, 1):
            response += f"{i}. **Номер:** `{phone}`\n"
            response += f"   **Сессия:** `{session_str[:30]}...`\n\n"
        
        await update.message.reply_text(response, parse_mode='Markdown')

    async def del_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, phone FROM sessions WHERE user_id = %s', (user_id,))
        sessions = cursor.fetchall()
        conn.close()
        
        if not sessions:
            await update.message.reply_text("❌ Нет сессий для удаления")
            return
        
        response = "🗑️ **Выбери сессию для удаления:**\n\n"
        for i, (session_id, phone) in enumerate(sessions, 1):
            response += f"{i}. {phone}\n"
        
        await update.message.reply_text(response)
        context.user_data['state'] = 'awaiting_delete'
        context.user_data['sessions_list'] = sessions

    async def process_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE, choice: str):
        if not choice.isdigit():
            await update.message.reply_text("❌ Введи номер сессии")
            return
        
        index = int(choice) - 1
        sessions_list = context.user_data.get('sessions_list', [])
        
        if index < 0 or index >= len(sessions_list):
            await update.message.reply_text("❌ Неверный номер")
            return
        
        session_id, phone = sessions_list[index]
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sessions WHERE id = %s', (session_id,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Сессия {phone} удалена")
        context.user_data.pop('state', None)
        context.user_data.pop('sessions_list', None)

    def run(self):
        self.app.run_polling(drop_pending_updates=True)
