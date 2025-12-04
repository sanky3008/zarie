#!/usr/bin/env python3
import os
import sys
import asyncio
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()

async def fetch_telegram_user(telegram_id):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not found")
        return None
    
    try:
        bot = Bot(token=token)
        chat = await bot.get_chat(chat_id=telegram_id)
        return {
            "id": chat.id,
            "username": chat.username,
            "first_name": chat.first_name,
            "last_name": chat.last_name
        }
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch_user_info.py <telegram_id>")
        sys.exit(1)
    
    user_data = asyncio.run(fetch_telegram_user(sys.argv[1]))
    
    if user_data:
        for key, value in user_data.items():
            if value is not None:
                print(f"{key}: {value}")
