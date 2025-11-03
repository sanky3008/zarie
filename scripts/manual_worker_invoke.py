#!/usr/bin/env python3
"""
Script to manually invoke a worker agent for hallucination correction.

USAGE:
1. Set the variables below (AGENT_NAME, USER_ID, MESSAGE)
2. Run: python scripts/manual_worker_invoke.py
   OR with railway: railway run python scripts/manual_worker_invoke.py
"""

import sys
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker_agent.agent.agent import WorkerAgent

# ===== CONFIGURE THESE VARIABLES =====
AGENT_NAME = "reading_reminder"  # Change this to your worker agent name
USER_ID = "7580670088"            # Change this to the user ID
MESSAGE = "This is a test message, don't do anything"  # Change this to your message
# =====================================

def main():
    load_dotenv()
    
    print(f"\n{'='*50}")
    print("Manual Worker Invocation Script")
    print(f"{'='*50}")
    print(f"Agent Name: {AGENT_NAME}")
    print(f"User ID: {USER_ID}")
    print(f"Message: {MESSAGE}")
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
            agent_name=AGENT_NAME,
            user_id=USER_ID,
            message=MESSAGE,
            medium="DEVELOPERS via MANUAL_INVOCATION",
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
