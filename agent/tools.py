from worker_agent.agent.agent import WorkerAgent
from worker_agent.directory.directory import Directory
import os
import asyncio
from fastmcp import Client

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Shared instances
_worker_agent = None
_directory = None
_mcp_tools_cache = None


class MCPManager:
    """Simple fastmcp wrapper for sync code."""
    
    def get_tools(self):
        """Get MCP tools (sync wrapper)."""
        global _mcp_tools_cache
        if _mcp_tools_cache:
            return _mcp_tools_cache
        
        async def _fetch():
            server_url = os.getenv("BRAVE_MCP_SERVER_URL")
            if not server_url:
                raise ValueError("BRAVE_MCP_SERVER_URL not set")
            
            client = Client(server_url)
            async with client:
                tools = await client.list_tools()
                return tools
        
        try:
            _mcp_tools_cache = asyncio.run(_fetch())
            return _mcp_tools_cache
        except Exception as e:
            print(f"Error fetching MCP tools: {e}")
            return []
    
    def call_tool(self, name, arguments):
        """Call MCP tool (sync wrapper). Returns string result."""
        async def _execute():
            server_url = os.getenv("BRAVE_MCP_SERVER_URL")
            if not server_url:
                raise ValueError("BRAVE_MCP_SERVER_URL not set")
            
            client = Client(server_url)
            async with client:
                result = await client.call_tool(name, arguments)
                # fastmcp returns CallToolResult - extract text content
                if hasattr(result, 'content') and result.content:
                    # Content is a list of ContentBlocks
                    texts = []
                    for content in result.content:
                        if hasattr(content, 'text'):
                            texts.append(content.text)
                    return "\n".join(texts) if texts else str(result)
                return str(result)
        
        try:
            return asyncio.run(_execute())
        except Exception as e:
            return f"Error calling {name}: {str(e)}"


def get_mcp_client_manager():
    """Get MCP client manager."""
    return MCPManager()


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
