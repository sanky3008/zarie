from agent.agent import Agent

def main():
    """Terminal chat application using the Agent."""
    user_id = "terminal_user_2"
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
        
        # Get response from agent
        response = agent.invoke(user_id, user_input, medium)
        
        # Display the response
        if response:
            print(f"\nDonna: {response['content']}")
        else:
            print("\nDonna: [No response]")

if __name__ == "__main__":
    main()
