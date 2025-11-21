import os
import asyncio
import logging
import signal
import sys
import threading
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_bot_in_thread(bot_name, bot_runner):
    """Запускает бота в отдельном потоке с собственным циклом событий"""
    def run():
        try:
            # Создаем новый цикл событий для этого потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            logger.info(f"Starting {bot_name}...")
            bot_runner()
        except Exception as e:
            logger.error(f"Error in {bot_name}: {e}")
            import time
            time.sleep(30)
            # Перезапускаем с новым циклом событий
            run_bot_in_thread(bot_name, bot_runner)
    
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread

def run_session_bot():
    from session_bot import SessionBot
    token = os.getenv('SESSION_BOT_TOKEN')
    if token:
        bot = SessionBot(token)
        bot.run()
    else:
        logger.error("SESSION_BOT_TOKEN not found")

def run_monitor_bot():
    from monitor_bot import MonitorBot
    token = os.getenv('MONITOR_BOT_TOKEN')
    if token:
        bot = MonitorBot(token)
        bot.run()
    else:
        logger.error("MONITOR_BOT_TOKEN not found")

def signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown"""
    logger.info("Received shutdown signal")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("Starting Telegram Session Manager...")
    
    # Проверяем только токены ботов
    required_vars = ['SESSION_BOT_TOKEN', 'MONITOR_BOT_TOKEN']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        sys.exit(1)
    
    if not os.getenv('DATABASE_URL'):
        logger.warning("DATABASE_URL not found, using SQLite as fallback")
    
    # Запускаем ботов в отдельных потоках с собственными циклами событий
    t1 = run_bot_in_thread("Session Bot", run_session_bot)
    t2 = run_bot_in_thread("Monitor Bot", run_monitor_bot)
    
    logger.info("Both bots started successfully")
    
    try:
        while True:
            if not t1.is_alive():
                logger.warning("Session Bot thread died, restarting...")
                t1 = run_bot_in_thread("Session Bot", run_session_bot)
                
            if not t2.is_alive():
                logger.warning("Monitor Bot thread died, restarting...")
                t2 = run_bot_in_thread("Monitor Bot", run_monitor_bot)
                
            # Используем time.sleep вместо asyncio.sleep в главном потоке
            import time
            time.sleep(60)
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Main loop error: {e}")
