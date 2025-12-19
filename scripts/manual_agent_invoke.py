#!/usr/bin/env python3
"""
Script to manually invoke the main Donna agent (Agent) for a user.
This script bypasses the usual message handling loop and allows manual injection of a prompt,
sending the response back to the user via their connected platform (Slack/Telegram).

USAGE:
1. Configure USER_ID and MESSAGE variables below.
2. Run: python scripts/manual_agent_invoke.py
"""

import sys
import os
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# --- CONFIGURATION START ---
USER_ID = ""  # Change this to the target User ID (Slack ID or Telegram ID)
MESSAGE = """
<dev_instructions>
This message is from developers. Please take the below message and pass it as it is to
the user on our behalf. Clearly call out that this message is from your creators. 
In case the user asks, we are reachable at sanky@zarie.chat/dk@zarie.chat
</dev_instructions>

Hey, thanks for using Zarie! Zarie might not be perfect right now and we saw that it couldn't help you out. 
We would love to get in touch with you to understand your requirements so that we can improve Zarie to better serve you. 
Can you please share your email ID in this chat, so that we can contact you?
""" 
# Change this to the message you want to send to the agent
# --- CONFIGURATION END ---


# Load environment variables
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent import Agent
from user_manager import get_user, user_exists

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    print(f"\n{'='*60}")
    print("Manual Agent Invocation Script")
    print(f"{'='*60}")
    print(f"User ID: {USER_ID}")
    print(f"Message: {MESSAGE.strip()}")
    print(f"{'='*60}\n")

    # 1. Environment & DB Checks
    print("🔍 Checking Environment & Database...")
    
    # Check for Prod DB usage safety
    if os.getenv("ENV") == "PROD" and not os.getenv("DATABASE_URL"):
         print("❌ Error: ENV is PROD but DATABASE_URL is missing!")
         sys.exit(1)
    
    if os.getenv("ENV") == "PROD":
        print("⚠️  WARNING: Running against PRODUCTION Database!")
    else:
        print("ℹ️  Running against LOCAL Database.")

    # 2. Fetch User
    print(f"\n👤 Fetching User [{USER_ID}]...")
    user = get_user(USER_ID)
    
    if not user:
        print(f"❌ Error: User {USER_ID} not found in database.")
        sys.exit(1)
        
    platform = user.get('platform', 'telegram') # Default to telegram if missing
    print(f"✓ User Found: {user.get('name')} (@{user.get('telegram_username')})")
    print(f"✓ Platform: {platform}")
    print(f"✓ Timezone: {user.get('timezone')}")

    # 3. Initialize Agent
    print("\n🤖 Initializing Agent...")
    try:
        agent = Agent()
        print("✓ Agent initialized.")
    except Exception as e:
        print(f"❌ Error initializing Agent: {e}")
        sys.exit(1)

    # 4. Invoke Agent
    print(f"\n🚀 Invoking Agent with message...")
    print(f"   > '{MESSAGE.strip()}'")
    
    # Use UTC timestamp
    timestamp = datetime.now(ZoneInfo("UTC"))
    user_timezone = user.get('timezone', 'Asia/Kolkata')
    team_id = user.get('team_id')
    
    full_response = ""
    
    try:
        async for chunk in agent.invoke(
            user_id=USER_ID,
            message=MESSAGE,
            medium=f"DEVELOPERS via MANUAL_INVOKE",
            timestamp=timestamp,
            user_timezone=user_timezone
        ):
            if chunk.strip():
                full_response += chunk
                print(f"\n📤 Delivering Chunk ({len(chunk)} chars)...")
                
                # 5. Send to Platform
                if platform == 'slack':
                    if not team_id:
                        print("❌ Error: User has no 'team_id'. Cannot fetch Slack token.")
                        continue
                        
                    await send_to_slack(USER_ID, chunk, team_id)
                elif platform == 'telegram':
                    await send_to_telegram(USER_ID, chunk)
                else:
                    print(f"❌ Error: Unknown platform '{platform}'. Cannot send message.")

    except Exception as e:
        print(f"\n\n❌ Error during execution: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n{'='*60}")
    print("✅ Done.")
    print(f"{'='*60}\n")


def get_slack_bot_token(team_id):
    """Fetch the Slack Bot Token for a given Team ID from the database."""
    from user_manager import get_db_connection
    
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        query = "SELECT bot_token FROM slack_bots WHERE team_id = %s" if db_type == 'postgres' else "SELECT bot_token FROM slack_bots WHERE team_id = ?"
        cursor.execute(query, (team_id,))
        result = cursor.fetchone()
        
        if result:
            return result[0]
        return None
    except Exception as e:
        print(f"❌ Error fetching Slack token: {e}")
        return None
    finally:
        conn.close()


async def send_to_slack(user_id, text, team_id):
    """Send message to Slack and log response using dynamic token."""
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    
    slack_token = get_slack_bot_token(team_id)
    
    if not slack_token:
        print(f"❌ Error: Could not find SLACK_BOT_TOKEN for Team ID: {team_id}")
        return

    client = WebClient(token=slack_token)
    
    try:
        # We need to find the DM channel/im ID since user_id might be the Member ID (U...)
        # chat_postMessage can take channel ID or Member ID for DMs in recent scopes, 
        # but let's be safe. Usually giving user_id as channel works for DMs in modern apps.
        response = client.chat_postMessage(
            channel=user_id,
            text=text
        )
        if response["ok"]:
            print(f"   ✓ [Slack] Success! (ts: {response['ts']})")
        else:
            print(f"   ✗ [Slack] Failed! Error: {response['error']}")
            
    except SlackApiError as e:
        print(f"   ✗ [Slack] Exception: {e.response['error']}")


async def send_to_telegram(user_id, text):
    """Send message to Telegram and log response."""
    from telegram import Bot
    from telegram.error import TelegramError
    
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        print("❌ Error: TELEGRAM_BOT_TOKEN not found in env.")
        return

    bot = Bot(token=telegram_token)
    
    try:
        # Telegram ID must be an integer usually
        try:
            chat_id = int(user_id)
        except ValueError:
            print(f"   ✗ [Telegram] Failed! User ID '{user_id}' is not an integer.")
            return

        message = await bot.send_message(chat_id=chat_id, text=text)
        print(f"   ✓ [Telegram] Success! (msg_id: {message.message_id})")
        
    except TelegramError as e:
         print(f"   ✗ [Telegram] Exception: {e}")


if __name__ == "__main__":
    asyncio.run(main())
