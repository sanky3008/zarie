
import asyncio
import os
import sys

# Add parent dir to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from run_scheduler import send_message
from dotenv import load_dotenv

load_dotenv()

async def verify():
    print("Starting verification...")
    # This should trigger the exception we injected in run_scheduler.py
    await send_message('test_user_verify', 'Test Message')
    print("Verification script finished.")

if __name__ == "__main__":
    asyncio.run(verify())
