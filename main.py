import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Запускает только Session Bot для начала"""
    logger.info("Starting Telegram Session Bot...")
    
    # Проверяем токен
    token = os.getenv('SESSION_BOT_TOKEN')
    if not token:
        logger.error("SESSION_BOT_TOKEN not found")
        return
    
    try:
        from session_bot import SessionBot
        bot = SessionBot(token)
        logger.info("Bot initialized, starting polling...")
        bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

if __name__ == "__main__":
    main()
