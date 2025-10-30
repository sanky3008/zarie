from worker_agent.agent.agent import WorkerAgent
from worker_agent.directory.directory import Directory

# Optional imports
PERPLEXITY_AVAILABLE = False
try:
    from perplexity import Perplexity
    PERPLEXITY_AVAILABLE = True
except ImportError:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Shared worker agent instance
_worker_agent = None
_directory = None

def get_worker_agent():
    """Get or create the shared worker agent instance."""
    global _worker_agent
    if _worker_agent is None:
        _worker_agent = WorkerAgent()
    return _worker_agent

def get_directory():
    """Get or create the shared directory instance."""
    global _directory
    if _directory is None:
        _directory = Directory()
    return _directory


def web_search(query: str):
    """
    Perform a web search using Perplexity API.
    
    Args:
        query (str): The search query
        
    Returns:
        str: Search results from Perplexity
    """
    if not PERPLEXITY_AVAILABLE:
        return f"Web search not available: {query}"
    
    client = Perplexity()
    
    completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": query,
            }
        ],
        model="sonar",
    )
    
    return completion.choices[0].message.content


def invoke_worker_agent(agent_name: str, user_id: str, purpose: str, message: str):
    """
    Create or invoke a worker agent to handle automated workflows and reminders.
    
    This tool allows you to delegate tasks to specialized worker agents that can:
    - Set up time-based reminders and recurring events
    - Execute automated workflows
    - Search the web for information
    - Maintain their own context and state
    
    Args:
        agent_name (str): Unique name for the worker agent (e.g., "reminder_agent", "cricket_tracker")
        user_id (str): User ID (will be injected automatically)
        purpose (str): Brief description of the agent's purpose (e.g., "Handle weekly reminders")
        message (str): The task or instruction to give to the worker agent
        
    Returns:
        str: Response from the worker agent
    """
    directory = get_directory()
    worker_agent = get_worker_agent()
    
    # Check if agent exists
    existing_agent = directory.get_agent(agent_name, user_id)
    
    if not existing_agent:
        # Create new agent
        directory.create_agent(
            agent_name=agent_name,
            user_id=user_id,
            purpose=purpose
        )
    
    # Invoke the agent with the message
    response = worker_agent.invoke(
        agent_name=agent_name,
        user_id=user_id,
        message=message,
        medium="MESSAGE_FROM_DONNA"
    )
    
    return response.get('content', 'No response from worker agent')

if __name__ == "__main__":
    print(web_search("dairy free hot chocolate restaurants Sarjapur Road Bangalore"))
