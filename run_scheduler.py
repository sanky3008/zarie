#!/usr/bin/env python3
"""
Railway CRON job to trigger time-based events and send reminders
"""
import asyncio
import os
from datetime import datetime
from telegram import Bot
from dotenv import load_dotenv

from event_manager.time_event_manager import get_due_events, update_next_trigger, disable_event
from worker_agent.agent.agent import WorkerAgent
from agent.agent import Agent

load_dotenv()

async def send_telegram_message(user_id: str, message: str):
    """Send a message to a user via Telegram"""
    bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))
    await bot.send_message(chat_id=user_id, text=message)

async def process_event(event, worker_agent, donna):
    """Process a single time event with timeout"""
    try:
        event_id = event['id']
        agent_name = event['agent_name']
        user_id = event['user_id']
        reminder_name = event['reminder_name']
        
        print(f"Processing: {reminder_name} for user {user_id}")
        
        # Add timeout to prevent hanging (60 seconds max per event)
        async def process_single_event():
            # Step 1: Invoke worker agent with system message
            system_message = f"REMINDER TRIGGERED: {event['message']}. Please execute the task and send the response back to Donna."
            worker_response = worker_agent.invoke(
                agent_name=agent_name,
                user_id=user_id,
                message=system_message,
                medium="system"
            )

            print(f"Worker response: {worker_response}")
            
            # Step 2: Send worker response to Donna
            donna_message = f"This is {agent_name}. {worker_response['content']}"
            donna_response = donna.invoke(
                user_id=user_id,
                message=donna_message,
                medium="system"
            )

            print(f"Donna response: {donna_response}")
            
            # Step 3: Send Donna's response to user via Telegram
            await send_telegram_message(user_id, donna_response['content'])
            
            # Step 4: Update or disable event
            if event['is_recurring'] and event['recurrence_rule']:
                update_next_trigger(event_id, event['recurrence_rule'])
                print(f"  ✓ Updated next trigger")
            else:
                disable_event(event_id)
                print(f"  ✓ Disabled one-time event")
        
        await asyncio.wait_for(process_single_event(), timeout=60)
    
    except asyncio.TimeoutError:
        print(f"  ✗ Timeout processing {event.get('reminder_name', 'unknown')}")
    except Exception as e:
        print(f"  ✗ Error: {e}")

async def main():
    """Main scheduler function with overall timeout"""
    print(f"\n🕐 Scheduler running at {datetime.now()}")
    
    try:
        # Maximum 4 minutes for entire job (Railway CRON runs every 5 mins)
        async def run_scheduler():
            # Get due events
            events = get_due_events()
            print(f"Found {len(events)} due event(s)")
            
            if not events:
                print("✓ No events to process\n")
                return
            
            # Initialize agents
            worker_agent = WorkerAgent()
            donna = Agent()
            
            # Process all events concurrently
            tasks = [process_event(event, worker_agent, donna) for event in events]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            print("✓ Scheduler completed\n")
        
        await asyncio.wait_for(run_scheduler(), timeout=240)
    
    except asyncio.TimeoutError:
        print("✗ Scheduler timeout - took longer than 4 minutes\n")
    except Exception as e:
        print(f"✗ Scheduler error: {e}\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Scheduler interrupted\n")
    except Exception as e:
        print(f"\n✗ Fatal error: {e}\n")
    finally:
        # Ensure script always exits cleanly
        print("Scheduler exiting...\n")

