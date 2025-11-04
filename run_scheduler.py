#!/usr/bin/env python3
"""
Railway CRON job to trigger time-based events and send reminders
"""
import sys
import asyncio
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

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

# Shared executor for agent invocations
_executor = None

def get_executor():
    """Get or create the shared thread pool executor."""
    global _executor
    if _executor is None:
        # Create executor with max_workers=20 for scheduler
        # This allows up to 20 concurrent event processing tasks
        _executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="scheduler-worker")
    return _executor

async def send_telegram_message(user_id: str, message: str):
    """Send a message to a user via Telegram"""
    bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))
    await bot.send_message(chat_id=user_id, text=message)

async def process_event(event, worker_agent, donna, executor):
    """Process a single time event with timeout"""
    try:
        agent_name = event['agent_name']
        user_id = event['user_id']
        reminders = event['reminders']  # dict with 'recurring' and 'non_recurring' lists
        
        recurring_reminders = reminders.get('recurring', [])
        non_recurring_reminders = reminders.get('non_recurring', [])
        all_reminders = recurring_reminders + non_recurring_reminders
        
        print(f"Processing: {len(all_reminders)} reminder(s) for agent '{agent_name}' (user {user_id})")
        
        # Add timeout to prevent hanging (180 seconds max per event)
        async def process_single_event():
            # Get trigger timestamp and convert to IST for context
            from dateutil.parser import parse
            trigger_time_utc = parse(all_reminders[0]['next_trigger_timestamp']) if isinstance(all_reminders[0]['next_trigger_timestamp'], str) else all_reminders[0]['next_trigger_timestamp']
            trigger_time_ist = utc_to_ist(trigger_time_utc)
            current_time_str = trigger_time_ist.strftime("%A, %B %d, %Y at %I:%M %p IST")
            
            # Build formatted reminder message
            reminder_text = "Reminder Triggered for the following time_events. Please find below the corresponding messages.\n\n"
            for reminder_obj in all_reminders:
                reminder_text += f"Name: {reminder_obj['reminder_name']}\nMessage: {reminder_obj['message']}\n\n"
            
            # Build medium string with all reminder names
            reminder_names = ", ".join([r['reminder_name'] for r in all_reminders])
            medium = f"REMINDER_TRIGGERED: {reminder_names}"
            
            loop = asyncio.get_event_loop()
            
            # Step 1: Invoke worker agent in thread pool (non-blocking)
            worker_response = await loop.run_in_executor(
                executor,
                worker_agent.invoke,
                agent_name,
                user_id,
                reminder_text,
                medium
            )

            print(f"Worker response: {worker_response}")
            
            # Check if worker response indicates no update needed
            if "Worker_Cron_Success_No_Update_Dont_Reply" in worker_response.get('content', ''):
                print("Skipping Donna invocation - no update needed")
                # Still update reminder statuses
                for reminder_obj in recurring_reminders:
                    update_next_trigger(reminder_obj['id'], reminder_obj['recurrence_rule'])
                    print(f"  ✓ Updated next trigger for recurring reminder: {reminder_obj['reminder_name']}")
                
                for reminder_obj in non_recurring_reminders:
                    disable_event(reminder_obj['id'])
                    print(f"  ✓ Disabled one-time reminder: {reminder_obj['reminder_name']}")
                
                return len(recurring_reminders) > 0
            
            # Step 2: Send worker response to Donna in thread pool (non-blocking)
            donna_message = f"{worker_response['content']}"
            donna_response = await loop.run_in_executor(
                executor,
                donna.invoke,
                user_id,
                donna_message,
                f"{agent_name}"
            )

            print(f"Donna response: {donna_response}")
            
            # Step 3: Send Donna's response to user via Telegram (async, non-blocking)
            await send_telegram_message(user_id, donna_response['content'])
            
            # Step 4: Handle each reminder based on its status
            for reminder_obj in recurring_reminders:
                update_next_trigger(reminder_obj['id'], reminder_obj['recurrence_rule'])
                print(f"  ✓ Updated next trigger for recurring reminder: {reminder_obj['reminder_name']}")
            
            for reminder_obj in non_recurring_reminders:
                disable_event(reminder_obj['id'])
                print(f"  ✓ Disabled one-time reminder: {reminder_obj['reminder_name']}")
            
            # Return whether we have any recurring events
            return len(recurring_reminders) > 0
        
        is_recurring = await asyncio.wait_for(process_single_event(), timeout=180)
        
        # On success, unlock ONLY recurring events (one-time events stay DISABLED)
        if is_recurring:
            for reminder_obj in recurring_reminders:
                update_event_status(reminder_obj['id'], 'ACTIVE')
    
    except asyncio.TimeoutError:
        print(f"  ✗ Timeout processing {event.get('agent_name', 'unknown')}")
        # Unlock all events to allow them to be retried on the next cycle
        for reminder_obj in reminders.get('recurring', []) + reminders.get('non_recurring', []):
            update_event_status(reminder_obj['id'], 'ACTIVE')
    except Exception as e:
        print(f"  ✗ Error: {e}")
        # Unlock all events to allow them to be retried on the next cycle
        for reminder_obj in reminders.get('recurring', []) + reminders.get('non_recurring', []):
            update_event_status(reminder_obj['id'], 'ACTIVE')

async def process_user_events(events, worker_agent, donna, executor):
    """Process multiple events for a single user sequentially to avoid race conditions"""
    for event in events:
        # Lock all event IDs (both recurring and non-recurring) to prevent reprocessing
        for reminder_obj in event['reminders'].get('recurring', []) + event['reminders'].get('non_recurring', []):
            update_event_status(reminder_obj['id'], 'PROCESSING')
        
        # Process event sequentially for this user
        await process_event(event, worker_agent, donna, executor)

async def check_and_process_events(worker_agent, donna, executor):
    """Check for due events and spawn background tasks to process them"""
    try:
        # Get due events
        events = get_due_events()
        
        if not events:
            print("✓ No events due")
            return
        
        print(f"Found {len(events)} due event(s)")
        
        # Group events by user_id to prevent race conditions
        user_events = {}
        for event in events:
            user_id = event['user_id']
            if user_id not in user_events:
                user_events[user_id] = []
            user_events[user_id].append(event)
        
        # Spawn one task per user (events for same user run sequentially)
        for user_id, user_event_list in user_events.items():
            asyncio.create_task(process_user_events(user_event_list, worker_agent, donna, executor))
            total_reminders = sum(
                len(e['reminders'].get('recurring', [])) + len(e['reminders'].get('non_recurring', []))
                for e in user_event_list
            )
            print(f"  → Spawned task for user {user_id}: {len(user_event_list)} event(s), {total_reminders} reminder(s)")
    
    except Exception as e:
        print(f"✗ Error checking events: {e}", flush=True)
        import traceback
        traceback.print_exc()

async def main():
    """Main scheduler - runs continuously, checking every minute"""
    print(f"\n🕐 Scheduler starting at {get_utc_now()} UTC", flush=True)
    print("Will check for events every 60 seconds...\n", flush=True)
    
    # Initialize agents once for the entire scheduler lifetime
    print("Initializing agents...", flush=True)
    worker_agent = WorkerAgent()
    donna = Agent()
    executor = get_executor()
    print("✓ Agents initialized\n", flush=True)
    
    check_count = 0
    
    while True:
        try:
            check_count += 1
            print(f"\n[Check #{check_count}] {get_utc_now()} UTC", flush=True)
            
            # Check and process events (non-blocking), reusing agent instances
            await check_and_process_events(worker_agent, donna, executor)
            
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

