import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient
from telethon.sessions import StringSession
import sqlite3
import asyncio
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sessions (
            user_id INTEGER,
            session_name TEXT,
            session_string TEXT,
            phone_number TEXT,
            is_active INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, session_name)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_filters (
            user_id INTEGER,
            session_name TEXT,
            filter_type TEXT,
            filter_value TEXT,
            PRIMARY KEY (user_id, session_name, filter_type)
        )
    ''')
    conn.commit()
    conn.close()

class SessionManagerBot:
    def __init__(self, token: str):
        self.token = token
        self.app = Application.builder().token(token).build()
        self.setup_handlers()
        init_db()

    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("add_session", self.add_session))
        self.app.add_handler(CommandHandler("list_sessions", self.list_sessions))
        self.app.add_handler(CommandHandler("delete_session", self.delete_session))
        self.app.add_handler(CommandHandler("set_filters", self.set_filters))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        welcome_text = """
🤖 **Бот управления Telegram сессиями**

Доступные команды:
/add_session - Добавить новую сессию
/list_sessions - Список ваших сессий
/delete_session - Удалить сессию
/set_filters - Настроить фильтры для мониторинга
        """
        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def add_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        await update.message.reply_text(
            "📱 Для создания новой сессии отправьте номер телефона в международном формате (например, +79123456789):"
        )
        context.user_data['awaiting_phone'] = True

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if context.user_data.get('awaiting_phone'):
            phone_number = update.message.text
            await self.create_session(update, context, phone_number)
            
        elif context.user_data.get('awaiting_code'):
            code = update.message.text
            await self.verify_code(update, context, code)
            
        elif context.user_data.get('awaiting_password'):
            password = update.message.text
            await self.verify_password(update, context, password)

    async def create_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE, phone_number: str):
        try:
            client = TelegramClient(StringSession(), api_id=YOUR_API_ID, api_hash=YOUR_API_HASH)
            await client.connect()
            
            context.user_data['client'] = client
            context.user_data['phone_number'] = phone_number
            context.user_data['awaiting_phone'] = False
            context.user_data['awaiting_code'] = True
            
            sent_code = await client.send_code_request(phone_number)
            context.user_data['phone_code_hash'] = sent_code.phone_code_hash
            
            await update.message.reply_text("🔐 Введите код подтверждения из Telegram:")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def verify_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
        try:
            client = context.user_data['client']
            phone_number = context.user_data['phone_number']
            phone_code_hash = context.user_data['phone_code_hash']
            
            await client.sign_in(phone_number, code, phone_code_hash=phone_code_hash)
            
            # Успешная авторизация
            session_string = client.session.save()
            
            # Сохраняем сессию в базу
            conn = sqlite3.connect('sessions.db')
            cursor = conn.cursor()
            session_name = f"session_{update.effective_user.id}_{len([s for s in cursor.execute('SELECT * FROM user_sessions WHERE user_id = ?', (update.effective_user.id,))]) + 1}"
            
            cursor.execute(
                'INSERT INTO user_sessions (user_id, session_name, session_string, phone_number) VALUES (?, ?, ?, ?)',
                (update.effective_user.id, session_name, session_string, phone_number)
            )
            conn.commit()
            conn.close()
            
            # Отправляем сессию пользователю
            await update.message.reply_text(
                f"✅ Сессия успешно создана!\n\n"
                f"Session string:\n`{session_string}`\n\n"
                f"Сохраните эту строку для использования в мониторинговом боте.",
                parse_mode='Markdown'
            )
            
            await client.disconnect()
            
            # Очищаем временные данные
            for key in ['client', 'phone_number', 'phone_code_hash', 'awaiting_code']:
                context.user_data.pop(key, None)
                
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при верификации: {str(e)}")

    async def list_sessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        
        sessions = cursor.execute(
            'SELECT session_name, phone_number, is_active FROM user_sessions WHERE user_id = ?',
            (user_id,)
        ).fetchall()
        
        if not sessions:
            await update.message.reply_text("❌ У вас нет активных сессий.")
            return
            
        session_list = "📋 Ваши сессии:\n\n"
        for session_name, phone, active in sessions:
            status = "✅ Активна" if active else "❌ Неактивна"
            session_list += f"• {session_name} ({phone}) - {status}\n"
            
        await update.message.reply_text(session_list)
        
        conn.close()

    def run(self):
        self.app.run_polling()

# Замените на ваши данные от my.telegram.org
YOUR_API_ID = 1234567
YOUR_API_HASH = "your_api_hash_here"

if __name__ == "__main__":
    bot = SessionManagerBot("YOUR_BOT_TOKEN_HERE")
    bot.run()
