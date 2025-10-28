#!/usr/bin/env python3
"""
Test the scheduler functionality (without actually sending Telegram messages)
"""
import asyncio
from datetime import datetime, timedelta

from event_manager.time_event_manager import get_due_events, update_next_trigger, disable_event
from worker_agent.agent.agent import WorkerAgent
from agent.agent import Agent
from worker_agent.agent.tools import set_time_event

async def test_scheduler():
    """Test the scheduler end-to-end"""
    print("🧪 Testing Scheduler Functionality\n")
    
    # Setup: Create a test reminder due now
    user_id = "test_user_123"
    agent_name = "test_scheduler_agent"
    
    print("1. Creating a test reminder due now...")
    next_trigger = datetime.now().isoformat()
    set_time_event(
        agent_name=agent_name,
        user_id=user_id,
        next_trigger_timestamp=next_trigger,
        is_recurring=False,
        reminder_name="test_scheduler_reminder",
        message="Test reminder message"
    )
    print("   ✓ Created\n")
    
    # Test: Get due events
    print("2. Getting due events...")
    events = get_due_events()
    test_events = [e for e in events if e['agent_name'] == agent_name]
    print(f"   Found {len(test_events)} test event(s)\n")
    
    if not test_events:
        print("   ✗ No test events found")
        return
    
    event = test_events[0]
    
    # Test: Process event (without Telegram sending)
    print("3. Processing event...")
    print(f"   Agent: {event['agent_name']}")
    print(f"   User: {event['user_id']}")
    print(f"   Message: {event['message']}\n")
    
    # Initialize agents
    worker_agent = WorkerAgent()
    donna = Agent()
    
    # Invoke worker agent
    print("4. Invoking worker agent...")
    system_message = f"REMINDER TRIGGERED: {event['message']}"
    worker_response = worker_agent.invoke(
        agent_name=event['agent_name'],
        user_id=event['user_id'],
        message=system_message,
        medium="system"
    )
    print(f"   Worker: {worker_response['content'][:100]}...\n")
    
    # Send to Donna
    print("5. Sending to Donna...")
    donna_message = f"This is {event['agent_name']}. {worker_response['content']}"
    donna_response = donna.invoke(
        user_id=event['user_id'],
        message=donna_message,
        medium="system"
    )
    print(f"   Donna: {donna_response['content'][:100]}...\n")
    
    # Clean up: Disable the test event
    print("6. Cleaning up...")
    disable_event(event['id'])
    print("   ✓ Disabled test event\n")
    
    print("✅ Scheduler test completed!")
    print(f"\nMessage that would be sent to Telegram:\n---\n{donna_response['content']}\n---")

if __name__ == "__main__":
    asyncio.run(test_scheduler())

