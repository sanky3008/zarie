
import sys
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent import Agent

def create_mock_message(role, content, created_at=None):
    if created_at is None:
        created_at = datetime.now(ZoneInfo("UTC")).isoformat()
    return {
        "role": role,
        "content": content,
        "created_at": created_at
    }

def test_format_history():
    agent_instance = Agent(db_path=":memory:")
    
    # Mock state and get_context
    # Create a sequence of messages
    messages = [
        create_mock_message("user", "User Msg 1 (5th last)"),
        create_mock_message("assistant", "Asst Msg 1"),
        create_mock_message("user", "User Msg 2 (4th last)"),
        create_mock_message("assistant", "Asst Msg 2"),
        create_mock_message("user", "User Msg 3 (3rd last)"), # Split point should be after this
        create_mock_message("assistant", "Asst Msg 3"),
        create_mock_message("user", "User Msg 4 (2nd last)"),
        create_mock_message("assistant", "Asst Msg 4"),
        create_mock_message("user", "User Msg 5 (last)"),
    ]
    
    agent_instance.state.get_context = lambda user_id: json.dumps(messages)
    
    # Mock get_system_prompt
    import agent.agent as agent_module
    original_get_system_prompt = agent_module.get_system_prompt
    agent_module.get_system_prompt = lambda user_id: "System Prompt"
    
    try:
        final_messages = agent_instance._prepare_messages("user123")
        
        print("--- Final Messages Structure ---")
        print(f"Total messages: {len(final_messages)}")
        print(f"First message role: {final_messages[0]['role']}")
        print(f"First message content (System): {final_messages[0]['content'][:100]}...")
        
        # Check if system prompt contains old history
        if "User Msg 1" in final_messages[0]['content']:
            print("SUCCESS: Old history found in system prompt.")
        else:
            print("FAILURE: Old history NOT found in system prompt.")
            
        # Check recent messages
        recent_count = len(final_messages) - 1
        print(f"Recent messages count: {recent_count}")
        
        if recent_count > 0:
            print(f"First recent message: {final_messages[1]}")
            if final_messages[1]['content'] == "Asst Msg 3":
                 print("SUCCESS: First recent message is correct (Asst Msg 3).")
            else:
                 print(f"FAILURE: First recent message is {final_messages[1]['content']}, expected 'Asst Msg 3'.")
                 
    finally:
        agent_module.get_system_prompt = original_get_system_prompt

    return final_messages

if __name__ == "__main__":
    test_format_history()
