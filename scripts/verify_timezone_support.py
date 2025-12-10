import asyncio
import sys
import os
from dotenv import load_dotenv

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from user_manager import create_or_update_user, get_user
from agent.agent import Agent

load_dotenv()

async def test_timezone_logic():
    print("=== Testing Timezone Support Logic ===\n")
    
    # 1. Setup a Test User
    test_user_id = "test_user_123"
    
    # Scenario A: London Time
    print("--- Scenario 1: User in London (Europe/London) ---")
    create_or_update_user(
        telegram_id=test_user_id,
        first_name="Sherlock",
        username="sherlock_holmes",
        platform="slack",
        timezone="Europe/London"
    )
    
    user = get_user(test_user_id)
    print(f"User in DB: {user['name']} | Timezone: {user['timezone']}")
    
    agent = Agent()
    print("Invoking Agent with: 'What is the current time and date?'")
    
    # We fetch the timezone logic internally in agent now, 
    # but we need to pass it to invoke mostly for the 'user_timezone' arg 
    # if we want to simulate the Bot's behavior exactly (which passes it in).
    user_timezone = user['timezone']
    
    print("Agent Response:")
    async for chunk in agent.invoke(test_user_id, "What is the current time and date?", "TEST_CONSOLE", user_timezone=user_timezone):
        print(chunk, end="", flush=True)
    print("\n")

    # Scenario B: Tokyo Time
    print("\n--- Scenario 2: User in Tokyo (Asia/Tokyo) ---")
    create_or_update_user(
        telegram_id=test_user_id,
        first_name="Sherlock",
        username="sherlock_holmes",
        platform="slack",
        timezone="Asia/Tokyo"
    )
    
    user = get_user(test_user_id) # Refresh
    print(f"User in DB: {user['name']} | Timezone: {user['timezone']}")
    
    user_timezone = user['timezone']
    
    print("Invoking Agent with: 'What is the current time and date?'")
    print("Agent Response:")
    async for chunk in agent.invoke(test_user_id, "What is the current time and date?", "TEST_CONSOLE", user_timezone=user_timezone):
        print(chunk, end="", flush=True)
    print("\n")

    print("\n")

    # Scenario 3: Setting a Reminder (Timezone Conversion Test)
    print("\n--- Scenario 3: Setting a Reminder (User: Asia/Tokyo) ---")
    # Current User is Tokyo (from Scenario 2)
    
    print("Invoking Agent with: 'Set a reminder for 'Check Timezone' in 2 minutes from now'")
    async for chunk in agent.invoke(test_user_id, "Set a reminder for 'Check Timezone' in 2 minutes from now", "TEST_CONSOLE", user_timezone=user_timezone):
        print(chunk, end="", flush=True)
    print("\n")
    
    # Verify DB content
    print("\n--- Verifying Database Content ---")
    from user_manager import get_db_connection
    conn, _ = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT next_trigger_timestamp, message FROM time_events WHERE user_id = ? AND reminder_name = 'Check Timezone'", (test_user_id,))
    row = cursor.fetchone()
    
    if row:
        stored_utc = row[0]
        print(f"✅ Found Reminder in DB!")
        print(f"Stored UTC Timestamp: {stored_utc}")
        print(f"Expected behavior: This UTC time should be approx 2 mins from now (real-world time), regardless of the user's virtual timezone being Tokyo.")
    else:
        print("❌ Reminder NOT found in DB.")
    conn.close()

if __name__ == "__main__":
    asyncio.run(test_timezone_logic())
