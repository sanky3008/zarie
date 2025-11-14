from agent.agent import Agent
from datetime import datetime
import asyncio

async def main():
    """Terminal chat application using the Agent."""
    user_id = "terminal_user_69"
    medium = "TERMINAL2"
    
    agent = Agent()
    
    print("Chat with Donna Paulsen (type 'exit' or 'quit' to end)")
    print("-" * 50)
    
    while True:
        # Get user input
        user_input = input("\nYou: ").strip()
        
        # Check for exit commands
        if user_input.lower() in ['exit', 'quit']:
            print("\nDonna: Later, boss.")
            break
        
        # Skip empty inputs
        if not user_input:
            continue
        
        # Stream response chunks as they arrive
        print("\nDonna: ", end="", flush=True)
        has_response = False
        async for chunk in agent.invoke(user_id, user_input, medium, datetime.now()):
            print(chunk, end="", flush=True)
            has_response = True
        
        if not has_response:
            print("[No response]")

if __name__ == "__main__":
    asyncio.run(main())
