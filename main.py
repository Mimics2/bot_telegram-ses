import os
import asyncio
import logging
import signal
import sys
from threading import Thread
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_bot(bot_name, bot_runner):
    """Запускает бота с обработкой ошибок"""
    try:
        logger.info(f"Starting {bot_name}...")
        bot_runner()
    except Exception as e:
        logger.error(f"Error in {bot_name}: {e}")
        # Перезапуск через 30 секунд
        import time
        time.sleep(30)
        run_bot(bot_name, bot_runner)

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
    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("Starting Telegram Session Manager...")
    
    # Проверяем обязательные переменные
    required_vars = ['SESSION_BOT_TOKEN', 'MONITOR_BOT_TOKEN', 'DATABASE_URL']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing environment variables: {missing_vars}")
        sys.exit(1)
    
    # Запускаем ботов в отдельных потоках
    t1 = Thread(target=lambda: run_bot("Session Bot", run_session_bot), daemon=True)
    t2 = Thread(target=lambda: run_bot("Monitor Bot", run_monitor_bot), daemon=True)
    
    t1.start()
    t2.start()
    
    logger.info("Both bots started successfully")
    
    # Бесконечный цикл с проверкой состояния
    try:
        while True:
            # Проверяем, живы ли потоки
            if not t1.is_alive():
                logger.warning("Session Bot thread died, restarting...")
                t1 = Thread(target=lambda: run_bot("Session Bot", run_session_bot), daemon=True)
                t1.start()
                
            if not t2.is_alive():
                logger.warning("Monitor Bot thread died, restarting...")
                t2 = Thread(target=lambda: run_bot("Monitor Bot", run_monitor_bot), daemon=True)
                t2.start()
                
            asyncio.sleep(60)  # Проверяем каждые 60 секунд
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Main loop error: {e}")
