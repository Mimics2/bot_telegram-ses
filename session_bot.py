import os
import logging
import sqlite3
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient
from telethon.sessions import StringSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SessionBot:
    def __init__(self, token: str):
        self.token = token
        self.app = Application.builder().token(token).build()
        self.setup_handlers()

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
        """
        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Простая проверка количества сессий через SQLite
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM sessions WHERE user_id = ?', (user_id,))
        session_count = cursor.fetchone()[0]
        conn.close()
        
        if session_count >= 3:
            await update.message.reply_text("❌ Максимум 3 сессии на пользователя")
            return
        
        await update.message.reply_text(
            "📱 **Создание новой сессии**\n\n"
            "Введите номер телефона в международном формате:\n"
            "Пример: +77777777777"
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
            client = TelegramClient(StringSession(), 6, "eb06d4abfb49dc3eeb1aeb98ae0f581e")
            await client.connect()
            
            sent_code = await client.send_code_request(phone)
            context.user_data['phone_code_hash'] = sent_code.phone_code_hash
            context.user_data['client'] = client
            
            await update.message.reply_text("✅ Код отправлен! Введите код из Telegram:")
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
                await update.message.reply_text("🔒 Введите пароль двухфакторной аутентификации:")
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
        session_string = client.session.save()
        user_id = update.effective_user.id
        
        # Сохраняем в SQLite
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO sessions (user_id, phone, session_string) VALUES (?, ?, ?)',
            (user_id, phone, session_string)
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ **Сессия создана!**\n\n"
            f"📱 Номер: `{phone}`\n"
            f"🔐 Сессия: `{session_string}`",
            parse_mode='Markdown'
        )
        
        await client.disconnect()
        # Очищаем контекст
        for key in ['state', 'phone', 'client', 'phone_code_hash']:
            context.user_data.pop(key, None)

    async def my_sessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        cursor.execute('SELECT phone, session_string FROM sessions WHERE user_id = ?', (user_id,))
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
        
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        cursor.execute('SELECT phone FROM sessions WHERE user_id = ?', (user_id,))
        sessions = cursor.fetchall()
        conn.close()
        
        if not sessions:
            await update.message.reply_text("❌ Нет сессий для удаления")
            return
        
        response = "🗑️ **Выбери сессию для удаления:**\n\n"
        for i, (phone,) in enumerate(sessions, 1):
            response += f"{i}. {phone}\n"
        
        await update.message.reply_text(response)
        context.user_data['state'] = 'awaiting_delete'
        context.user_data['sessions_list'] = [phone for phone, in sessions]

    async def process_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE, choice: str):
        if not choice.isdigit():
            await update.message.reply_text("❌ Введи номер сессии")
            return
        
        index = int(choice) - 1
        sessions_list = context.user_data.get('sessions_list', [])
        
        if index < 0 or index >= len(sessions_list):
            await update.message.reply_text("❌ Неверный номер")
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
        
        await update.message.reply_text(f"✅ Сессия {phone_to_delete} удалена")
        context.user_data.pop('state', None)
        context.user_data.pop('sessions_list', None)

    def run(self):
        # Инициализируем базу данных
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
        
        self.app.run_polling(drop_pending_updates=True)
