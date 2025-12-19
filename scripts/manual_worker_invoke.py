#!/usr/bin/env python3
"""
Script to manually invoke a worker agent for hallucination correction.

USAGE:
1. Set the variables below (AGENT_NAME, USER_ID, MESSAGE)
2. Run: python scripts/manual_worker_invoke.py
"""

import sys
import os
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import litellm
# litellm.set_verbose = True

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker_agent.agent.agent import WorkerAgent

AGENT_NAME = "cricket_reminder"  # Change this to your worker agent name
USER_ID = "8147318773"            # Change this to the user ID
MESSAGE = """
You misinterpreted user's request, user wanted every 10 mins update until RCB's purse goes down to 20L or if the auction ends, until then user wanted 10 mins update for RCB auction, along with every 30 mins update for big moves in the auction and updates on top player's auction details.
"""  
# Change this to your message

async def main():
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
        response = await worker_agent.invoke(
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
    asyncio.run(main())
