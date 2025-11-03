#!/usr/bin/env python3
"""
Script to manually invoke a worker agent for hallucination correction.

USAGE:
  python scripts/manual_worker_invoke.py <agent_name> <user_id> "<message>"
  
  Or with flags:
  python scripts/manual_worker_invoke.py --agent-name reading_reminder --user-id 7580670088 --message "Your message here"
  
EXAMPLES:
  python scripts/manual_worker_invoke.py reading_reminder 7580670088 "Set a reminder for tomorrow at 2pm"
  railway run python scripts/manual_worker_invoke.py reminder_agent user_123 "Delete the meeting"
"""

import sys
import os
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker_agent.agent.agent import WorkerAgent

def main():
    parser = argparse.ArgumentParser(
        description="Manually invoke a worker agent for corrections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/manual_worker_invoke.py reading_reminder 7580670088 "Test message"
  railway run python scripts/manual_worker_invoke.py reminder_agent user_123 "Set reminder"
        """
    )
    
    parser.add_argument(
        "agent_name",
        help="Name of the worker agent to invoke"
    )
    parser.add_argument(
        "user_id",
        help="User ID to invoke the agent for"
    )
    parser.add_argument(
        "message",
        help="Message to send to the agent"
    )
    
    args = parser.parse_args()
    
    load_dotenv()
    
    print(f"\n{'='*50}")
    print("Manual Worker Invocation Script")
    print(f"{'='*50}")
    print(f"Agent Name: {args.agent_name}")
    print(f"User ID: {args.user_id}")
    print(f"Message: {args.message}")
    print(f"{'='*50}\n")
    
    try:
        # Create worker agent instance
        print("🔄 Creating worker agent instance...")
        worker_agent = WorkerAgent()
        
        # Invoke with current UTC timestamp
        timestamp = datetime.now(ZoneInfo("UTC"))
        
        print("📤 Invoking worker agent...\n")
        
        # Call invoke method
        response = worker_agent.invoke(
            agent_name=args.agent_name,
            user_id=args.user_id,
            message=args.message,
            medium="MANUAL_INVOCATION",
            timestamp=timestamp
        )
        
        print(f"\n{'='*50}")
        print("✓ Response:")
        print(f"{'='*50}")
        print(f"{response['content']}")
        print(f"{'='*50}\n")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
