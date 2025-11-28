import sys
import os
import json
import argparse
from dotenv import load_dotenv

# Add the project root to sys.path to allow imports from agent
# Assuming this script is in tests/ and agent is in agent/
# Root is one level up from tests/
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from agent.agent import Agent

def main():
    parser = argparse.ArgumentParser(description="Check context size for a user.")
    parser.add_argument("user_id", help="User ID to check context for")
    parser.add_argument("--db-path", help="Path to local DB (optional, overrides default if supported)")
    
    args = parser.parse_args()
    
    # Load .env from project root
    load_dotenv(os.path.join(project_root, ".env"))
    
    # Get ENV variable from environment, default to LOCAL
    env = os.getenv("ENV", "LOCAL").upper()
    
    print(f"Environment: {env}")
    if env == "PROD":
        if not os.getenv("DATABASE_URL"):
            print("WARNING: DATABASE_URL not found in environment for PROD.")
    
    try:
        # Initialize Agent
        # Note: The State class has specific logic for DB paths. 
        # We pass db_path if provided, but State might use its shared pool logic.
        agent = Agent(db_path=args.db_path)
        
        print(f"Fetching context for user_id: {args.user_id}")
        
        # Access the private method _prepare_messages to get the exact list sent to LLM
        # This includes system prompt, history formatting, and recent messages
        messages = agent._prepare_messages(args.user_id)
        
        if not messages:
            print("No messages found or empty context.")
            return

        # Calculate size
        # We dump to JSON to estimate the payload size
        json_dump = json.dumps(messages, ensure_ascii=False)
        char_count = len(json_dump)
        rough_tokens = char_count / 4
        
        print("\n" + "="*50)
        print(f"CONTEXT REPORT FOR USER: {args.user_id}")
        print("="*50)
        print(f"Total Messages: {len(messages)}")
        print(f"Total Characters: {char_count}")
        print(f"Rough Token Estimate (~chars/4): {int(rough_tokens)}")
        print("-" * 50)
        
        # Breakdown
        system_msgs = [m for m in messages if m["role"] == "system"]
        user_msgs = [m for m in messages if m["role"] == "user"]
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        
        print(f"Message Breakdown:")
        print(f"  System: {len(system_msgs)}")
        print(f"  User: {len(user_msgs)}")
        print(f"  Assistant: {len(assistant_msgs)}")
        print(f"  Tool: {len(tool_msgs)}")
        
        if system_msgs:
            sys_content = system_msgs[0].get("content", "")
            print(f"\nSystem Prompt Length: {len(sys_content)} chars")
            print(f"System Prompt Tokens: ~{int(len(sys_content)/4)}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
