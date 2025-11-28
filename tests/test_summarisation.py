import asyncio
import os
import sys
import json
from datetime import datetime
from zoneinfo import ZoneInfo

# Add parent directory to path to import agent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent import Agent
from agent.state.state import State

async def test_summarisation():
    print("Starting summarisation test...")
    
    # Use a test user ID
    user_id = "test_summary_user_v1"
    
    # Initialize Agent (which initializes State)
    # Point to the correct DB
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'chats.db')
    # Make sure we are using the local DB for this test
    os.environ['ENV'] = 'LOCAL' 
    
    agent = Agent(db_path=db_path)
    state = agent.state
    
    # Clear existing context for this user (if any)
    # We can't easily delete from here without direct DB access, but let's assume new user or just append
    # Actually, let's use a unique user_id based on timestamp to avoid conflicts
    import time
    user_id = f"test_summary_{int(time.time())}"
    print(f"Using test user: {user_id}")
    
    # Ensure user exists in users table for update_running_summary to work
    # We can use raw cursor execution since we have access to state's connection/cursor
    if state.db_type == 'sqlite':
        with state.lock:
            state.cursor.execute("INSERT OR IGNORE INTO users (telegram_id, name) VALUES (?, ?)", (user_id, "Test User"))
            state.conn.commit()
    else:
        # Postgres
        conn = state.pool.getconn()
        try:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO users (telegram_id, name) VALUES (%s, %s) ON CONFLICT (telegram_id) DO NOTHING", (user_id, "Test User"))
            conn.commit()
        finally:
            state.pool.putconn(conn)
    
    # 1. Insert > 500 dummy messages
    print("Inserting 550 dummy messages...")
    messages = []
    for i in range(550):
        messages.append({
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"This is message number {i}. Some content here to summarise.",
            "created_at": datetime.now(ZoneInfo("UTC")).isoformat()
        })
    
    # Add them in batches to avoid huge SQL queries if needed, but add_context handles list
    state.add_context(user_id, messages)
    
    # Verify insertion
    context = state.get_context(user_id)
    loaded_msgs = json.loads(context)
    print(f"Inserted {len(loaded_msgs)} messages.")
    assert len(loaded_msgs) == 550
    
    # 2. Trigger _prepare_messages
    # This should trigger summarization because 550 > 500 (and split index will be around 544)
    print("Triggering _prepare_messages (should trigger summarisation)...")
    
    # Mock summarise_context to avoid API call
    from unittest.mock import patch, MagicMock
    
    # We need to patch where it is IMPORTED. 
    # Since it is imported INSIDE the function `_prepare_messages` with `from agent.summarisation import summarise_context`,
    # we have to patch `agent.summarisation.summarise_context`.
    
    async def mock_summarise(state, user_id, messages):
        print("Mock summarisation called!")
        summary = "This is a mock summary of the conversation."
        state.update_running_summary(user_id, summary)
        
        # Logic from summarisation.py to mark messages
        max_seq = -1
        for msg in messages:
            if 'message_sequence' in msg:
                seq = msg['message_sequence']
                if seq > max_seq:
                    max_seq = seq
        
        if max_seq != -1:
            state.mark_messages_up_to_sequence(user_id, max_seq)
            
        return summary

    with patch('agent.summarisation.summarise_context', side_effect=mock_summarise) as mock:
        try:
            prepared_messages = await agent._prepare_messages(user_id)
            print("Summarisation triggered successfully.")
        except Exception as e:
            print(f"Error during _prepare_messages: {e}")
            raise e
            
    # 3. Verify DB updates
    # Check running summary
    summary = state.get_running_summary(user_id)
    print(f"Running summary: {summary}")
    
    # Check is_summarised flag
    new_context = state.get_context(user_id)
    new_loaded_msgs = json.loads(new_context) if new_context else []
    print(f"Messages in context after summarisation: {len(new_loaded_msgs)}")
    
    if summary == "This is a mock summary of the conversation.":
        if len(new_loaded_msgs) < 100:
            print("SUCCESS: Context size reduced significantly and summary updated.")
        else:
            print(f"FAILURE: Context size did not reduce. Count: {len(new_loaded_msgs)}")
    else:
        print("FAILURE: Summary not updated correctly.")

if __name__ == "__main__":
    asyncio.run(test_summarisation())
