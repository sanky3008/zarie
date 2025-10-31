#!/usr/bin/env python3
"""
Railway CRON job to trigger time-based events and send reminders
"""
import sys
import asyncio
import os
from datetime import datetime

print("=== SCHEDULER STARTING ===", flush=True)

try:
    from telegram import Bot
    from dotenv import load_dotenv
    from event_manager.time_event_manager import get_due_events, update_next_trigger, disable_event, get_utc_now, utc_to_ist, update_event_status
    from worker_agent.agent.agent import WorkerAgent
    from agent.agent import Agent
    print("✓ All imports successful", flush=True)
except Exception as e:
    print(f"✗ Import error: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

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
        reminder_message = event['message']
        
        print(f"Processing: {reminder_name} for user {user_id}")
        
        # Add timeout to prevent hanging (180 seconds max per event)
        async def process_single_event():
            # Get trigger timestamp and convert to IST for context
            from dateutil.parser import parse
            trigger_time_utc = parse(event['next_trigger_timestamp']) if isinstance(event['next_trigger_timestamp'], str) else event['next_trigger_timestamp']
            trigger_time_ist = utc_to_ist(trigger_time_utc)
            current_time_str = trigger_time_ist.strftime("%A, %B %d, %Y at %I:%M %p IST")
            
            # Step 1: Invoke worker agent with system message
            worker_response = worker_agent.invoke(
                agent_name=agent_name,
                user_id=user_id,
                message=reminder_message,
                medium=f"REMINDER_TRIGGERED: {agent_name}"
            )

            print(f"Worker response: {worker_response}")
            
            # Step 2: Send worker response to Donna
            donna_message = f"{worker_response['content']}"
            donna_response = donna.invoke(
                user_id=user_id,
                message=donna_message,
                medium=f"{agent_name}"
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
        
        await asyncio.wait_for(process_single_event(), timeout=180)
        
        # On success, unlock the event for the next run
        update_event_status(event_id, 'ACTIVE')
    
    except asyncio.TimeoutError:
        print(f"  ✗ Timeout processing {event.get('reminder_name', 'unknown')}")
        # Unlock the event to allow it to be retried on the next cycle
        update_event_status(event_id, 'ACTIVE')
    except Exception as e:
        print(f"  ✗ Error: {e}")
        # Unlock the event to allow it to be retried on the next cycle
        update_event_status(event_id, 'ACTIVE')

async def check_and_process_events():
    """Check for due events and spawn background tasks to process them"""
    try:
        # Get due events
        events = get_due_events()
        
        if not events:
            print("✓ No events due")
            return
        
        print(f"Found {len(events)} due event(s)")
        
        # Initialize agents once per check
        worker_agent = WorkerAgent()
        donna = Agent()
        
        # Lock and spawn tasks
        for event in events:
            # Lock the event to prevent reprocessing
            update_event_status(event['id'], 'PROCESSING')
            
            # Spawn a background task to handle the event
            asyncio.create_task(process_event(event, worker_agent, donna))
            print(f"  → Spawned task for: {event['reminder_name']}")
    
    except Exception as e:
        print(f"✗ Error checking events: {e}", flush=True)
        import traceback
        traceback.print_exc()

async def main():
    """Main scheduler - runs continuously, checking every minute"""
    print(f"\n🕐 Scheduler starting at {get_utc_now()} UTC", flush=True)
    print("Will check for events every 60 seconds...\n", flush=True)
    
    check_count = 0
    
    while True:
        try:
            check_count += 1
            print(f"\n[Check #{check_count}] {get_utc_now()} UTC", flush=True)
            
            # Check and process events (non-blocking)
            await check_and_process_events()
            
            # Wait 60 seconds before next check
            await asyncio.sleep(60)
            
        except KeyboardInterrupt:
            print("\n⚠️  Scheduler interrupted by user", flush=True)
            break
        except Exception as e:
            print(f"✗ Scheduler error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            # Continue running even if there's an error
            await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Scheduler interrupted\n", flush=True)
    except Exception as e:
        print(f"\n✗ Fatal error: {e}\n", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        # Ensure script always exits cleanly
        print("Scheduler exiting...\n", flush=True)

