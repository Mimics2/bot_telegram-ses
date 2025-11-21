import os
import asyncio
import logging
from threading import Thread
from dotenv import load_dotenv

load_dotenv()

# Запускаем обоих ботов в одном процессе
def run_session_bot():
    from session_bot import SessionBot
    token = os.getenv('SESSION_BOT_TOKEN')
    if token:
        bot = SessionBot(token)
        bot.run()
    else:
        logging.error("SESSION_BOT_TOKEN not found")

def run_monitor_bot():
    from monitor_bot import MonitorBot
    token = os.getenv('MONITOR_BOT_TOKEN')
    if token:
        bot = MonitorBot(token)
        bot.run()
    else:
        logging.error("MONITOR_BOT_TOKEN not found")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Запускаем ботов в отдельных потоках
    t1 = Thread(target=run_session_bot, daemon=True)
    t2 = Thread(target=run_monitor_bot, daemon=True)
    
    t1.start()
    t2.start()
    
    # Бесконечный цикл чтобы приложение не закрывалось
    try:
        while True:
            asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
