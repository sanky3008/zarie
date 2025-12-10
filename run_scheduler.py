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

async def send_message(user_id: str, message: str):
    """Send a message to a user via their preferred platform (Telegram or Slack)"""
    from user_manager import get_user, set_user_blocked
    from event_manager.time_event_manager import disable_all_user_events
    
    user = get_user(user_id)
    platform = user.get('platform', 'telegram') if user else 'telegram'
    
    if platform == 'slack':
        team_id = user.get('team_id')
        if not team_id:
            print(f"Error: Slack user {user_id} missing team_id")
            return
            
        # Fetch bot token from DB
        from user_manager import get_db_connection
        conn, db_type = get_db_connection()
        cursor = conn.cursor()
        try:
            query = "SELECT bot_token FROM slack_bots WHERE team_id = %s" if db_type == 'postgres' else "SELECT bot_token FROM slack_bots WHERE team_id = ?"
            cursor.execute(query, (team_id,))
            result = cursor.fetchone()
            if not result:
                print(f"Error: No bot token found for team_id {team_id}")
                return
            slack_token = result[0]
        except Exception as e:
            print(f"Error fetching Slack token: {str(e)}")
            return
        finally:
            conn.close()

        try:
            from slack_sdk.web.async_client import AsyncWebClient
            from slack_sdk.errors import SlackApiError
            client = AsyncWebClient(token=slack_token)
            await client.chat_postMessage(channel=user_id, text=message)
        except SlackApiError as e:
            error_msg = str(e)
            if "account_inactive" in error_msg or "channel_not_found" in error_msg:
                 print(f"⚠️ User {user_id} seems to have blocked/removed the bot (Slack error: {e.response['error']}). Disabling events.")
                 set_user_blocked(user_id, True)
                 disable_all_user_events(user_id)
            else:
                print(f"Error sending Slack message to {user_id}: {e}")
        except Exception as e:
            print(f"Error sending Slack message to {user_id}: {e}")
            
    else:
        # Default to Telegram
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not token:
            print(f"Error: TELEGRAM_BOT_TOKEN not found for user {user_id}")
            return
            
        try:
            bot = Bot(token=token)
            await bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            # Handle blocked user
            # telegram.error.Forbidden is the specific error, but we catch generic Exception to be safe
            # and check the string content as we didn't import the specific error class at top level
            error_str = str(e)
            if "Forbidden" in error_str or "bot was blocked" in error_str or "user is deactivated" in error_str:
                print(f"⚠️ User {user_id} has blocked the bot. Disabling events.")
                set_user_blocked(user_id, True)
                disable_all_user_events(user_id)
            else:
                print(f"Error sending Telegram message to {user_id}: {e}")

async def process_event(event, worker_agent, donna):
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
            # context
            from dateutil.parser import parse
            from zoneinfo import ZoneInfo
            
            # Fetch user timezone
            user_data = get_user(user_id)
            user_timezone = user_data.get('timezone', 'Asia/Kolkata') if user_data else 'Asia/Kolkata'
            
            trigger_time_utc = parse(all_reminders[0]['next_trigger_timestamp']) if isinstance(all_reminders[0]['next_trigger_timestamp'], str) else all_reminders[0]['next_trigger_timestamp']
            
            # Convert to user timezone
            if trigger_time_utc.tzinfo is None:
                 trigger_time_utc = trigger_time_utc.replace(tzinfo=ZoneInfo("UTC"))
            
            try:
                trigger_time_local = trigger_time_utc.astimezone(ZoneInfo(user_timezone))
            except Exception:
                trigger_time_local = trigger_time_utc.astimezone(ZoneInfo("Asia/Kolkata")) # Fallback
                
            current_time_str = trigger_time_local.strftime(f"%A, %B %d, %Y at %I:%M %p {user_timezone}")
            
            # Build formatted reminder message
            reminder_text = "Reminder Triggered for the following time_events. Please find below the corresponding messages.\n\n"
            for reminder_obj in all_reminders:
                reminder_text += f"Name: {reminder_obj['reminder_name']}\nMessage: {reminder_obj['message']}\n\n"
            
            # Build medium string with all reminder names
            reminder_names = ", ".join([r['reminder_name'] for r in all_reminders])
            medium = f"REMINDER_TRIGGERED: {reminder_names}"
            
            # Step 1: Direct async call to worker agent
            worker_response = await worker_agent.invoke(
                agent_name,
                user_id,
                reminder_text,
                medium,
                user_timezone=user_timezone
            )

            print(f"Worker response: {worker_response}")
            
            # Check if worker response indicates no update needed
            if "Worker_Cron_Success_No_Update_Dont_Reply" in worker_response.get('content', ''):
                print("Skipping Donna invocation - no update needed")
                # Still update reminder statuses
                active_recurring_ids = []
                for reminder_obj in recurring_reminders:
                    is_active = update_next_trigger(reminder_obj['id'], reminder_obj['recurrence_rule'])
                    if is_active:
                        active_recurring_ids.append(reminder_obj['id'])
                        print(f"  ✓ Updated next trigger for recurring reminder: {reminder_obj['reminder_name']}")
                    else:
                        print(f"  ✓ Disabled recurring reminder (COUNT exhausted): {reminder_obj['reminder_name']}")
                
                for reminder_obj in non_recurring_reminders:
                    disable_event(reminder_obj['id'])
                    print(f"  ✓ Disabled one-time reminder: {reminder_obj['reminder_name']}")
                
                # Update status back to ACTIVE for recurring reminders before returning
                for event_id in active_recurring_ids:
                    update_event_status(event_id, 'ACTIVE')
                
                return len(active_recurring_ids) > 0, active_recurring_ids
            
            # Step 2: Stream response from Donna and send chunks to Telegram
            donna_message = f"{worker_response['content'].replace('**', '')}"
            accumulated_response = ""
            
            print("Streaming Donna response:")
            async for chunk in donna.invoke(
                user_id,
                donna_message,
                f"{agent_name}",
                trigger_time_utc,
                user_timezone
            ):
                accumulated_response += chunk
                # Send each chunk to user immediately
                await send_message(user_id, chunk)
                print(f"  → Sent chunk to user: {chunk[:30]}...")
            
            donna_response = {"content": accumulated_response}
            print(f"Donna response complete: {len(accumulated_response)} characters")
            
            # Step 4: Handle each reminder based on its status
            active_recurring_ids = []
            for reminder_obj in recurring_reminders:
                is_active = update_next_trigger(reminder_obj['id'], reminder_obj['recurrence_rule'])
                if is_active:
                    active_recurring_ids.append(reminder_obj['id'])
                    print(f"  ✓ Updated next trigger for recurring reminder: {reminder_obj['reminder_name']}")
                else:
                    print(f"  ✓ Disabled recurring reminder (COUNT exhausted): {reminder_obj['reminder_name']}")
            
            for reminder_obj in non_recurring_reminders:
                disable_event(reminder_obj['id'])
                print(f"  ✓ Disabled one-time reminder: {reminder_obj['reminder_name']}")
            
            # Return whether we have any active recurring events
            return len(active_recurring_ids) > 0, active_recurring_ids
        
        is_recurring, active_recurring_ids = await asyncio.wait_for(process_single_event(), timeout=180)
        
        # On success, unlock ONLY active recurring events (one-time events stay DISABLED)
        if is_recurring:
            for event_id in active_recurring_ids:
                update_event_status(event_id, 'ACTIVE')
    
    except asyncio.TimeoutError:
        print(f"  ✗ Timeout processing {event.get('agent_name', 'unknown')}")
        # Unlock all events to allow them to be retried on the next cycle
        for reminder_obj in reminders.get('recurring', []) + reminders.get('non_recurring', []):
            update_event_status(reminder_obj['id'], 'ACTIVE')
    except Exception as e:
        print(f"  ✗ Error: {e}")
        # If error is "Chat not found", process reminders as usual
        if "Chat not found" in str(e):
            active_recurring_ids = []
            for reminder_obj in reminders.get('recurring', []):
                is_active = update_next_trigger(reminder_obj['id'], reminder_obj['recurrence_rule'])
                if is_active:
                    active_recurring_ids.append(reminder_obj['id'])
                else:
                    pass
            
            for reminder_obj in reminders.get('non_recurring', []):
                disable_event(reminder_obj['id'])
            
            # Update status back to ACTIVE for recurring reminders
            for event_id in active_recurring_ids:
                update_event_status(event_id, 'ACTIVE')
        else:
            # Unlock all events to allow them to be retried on the next cycle
            for reminder_obj in reminders.get('recurring', []) + reminders.get('non_recurring', []):
                update_event_status(reminder_obj['id'], 'ACTIVE')

async def process_user_events(events, worker_agent, donna):
    """Process multiple events for a single user sequentially to avoid race conditions"""
    for event in events:
        # Lock all event IDs (both recurring and non-recurring) to prevent reprocessing
        for reminder_obj in event['reminders'].get('recurring', []) + event['reminders'].get('non_recurring', []):
            update_event_status(reminder_obj['id'], 'PROCESSING')
        
        # Process event sequentially for this user
        await process_event(event, worker_agent, donna)

async def check_and_process_events(worker_agent, donna):
    """Check for due events and spawn background tasks to process them"""
    try:
        print(f"Checking for due events at {get_utc_now()}...")
        # Get due events
        events = get_due_events()
        print(f"get_due_events returned: {len(events)} events")
        
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
            asyncio.create_task(process_user_events(user_event_list, worker_agent, donna))
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
    print("✓ Agents initialized\n", flush=True)
    
    check_count = 0
    
    while True:
        try:
            check_count += 1
            print(f"\n[Check #{check_count}] {get_utc_now()} UTC", flush=True)
            
            # Check and process events (non-blocking), reusing agent instances
            await check_and_process_events(worker_agent, donna)
            
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

