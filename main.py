import asyncio
import logging
from telegram_bot import TelegramBot
from slack_app.bot import SlackBot
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def main():
    load_dotenv()
    
    # Initialize bots
    telegram_bot = TelegramBot()
    slack_bot = SlackBot()
    
    print("Starting Zarie on Telegram and Slack...")
    
    # Run both bots concurrently
    # telegram_bot.start() starts the updater but returns (non-blocking)
    # slack_bot.start() runs the socket mode handler (blocking)
    
    await telegram_bot.start()
    await slack_bot.start() # This blocks until stop signal

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopping bots...")
