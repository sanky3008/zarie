from worker_agent.agent.agent import WorkerAgent
from worker_agent.directory.directory import Directory
import os
import asyncio
from fastmcp import Client
from telegram import Bot

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
    """Async fastmcp wrapper."""
    
    async def get_tools(self):
        """Get MCP tools (async)."""
        global _mcp_tools_cache
        if _mcp_tools_cache:
            return _mcp_tools_cache
        
        server_url = os.getenv("BRAVE_MCP_SERVER_URL")
        if not server_url:
            raise ValueError("BRAVE_MCP_SERVER_URL not set")
        
        try:
            client = Client(server_url)
            async with client:
                _mcp_tools_cache = await client.list_tools()
                return _mcp_tools_cache
        except Exception as e:
            print(f"Error fetching MCP tools: {e}")
            return []
    
    async def call_tool(self, name, arguments):
        """Call MCP tool (async). Returns string result."""
        server_url = os.getenv("BRAVE_MCP_SERVER_URL")
        if not server_url:
            raise ValueError("BRAVE_MCP_SERVER_URL not set")
        
        try:
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


async def invoke_worker_agent(agent_name: str, user_id: str, purpose: str, message: str, user_timezone: str = 'Asia/Kolkata'):
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
        user_timezone (str): The user's timezone (injected automatically).
        
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
    
    # Invoke the agent with the message (now async)
    response = await worker_agent.invoke(
        agent_name=agent_name,
        user_id=user_id,
        message=message,
        medium="MESSAGE_FROM_Zarie",
        user_timezone=user_timezone
    )
    
    content = response.get('content', 'No response from worker agent')
    return content.replace('**', '') if isinstance(content, str) else content


async def send_message_to_user(user_id: str, message: str):
    """
    Send a message to the user immediately.
    
    Use this tool to provide updates to the user when a task is taking time or to keep them informed
    without waiting for the final response. This does NOT break the agent's thought process loop.
    
    Args:
        user_id (str): The user's ID (Telegram ID or Slack User ID, injected automatically).
        message (str): The message content to send to the user.
        
    Returns:
        str: Status of the message sending.
    """
    from user_manager import get_user
    
    # Get user platform
    user = get_user(user_id)
    platform = user.get('platform', 'telegram') if user else 'telegram'
    
    if platform == 'slack':
        team_id = user.get('team_id')
        if not team_id:
            return "Error: Slack user missing team_id"
            
        # Fetch bot token from DB
        from user_manager import get_db_connection
        conn, db_type = get_db_connection()
        cursor = conn.cursor()
        try:
            query = "SELECT bot_token FROM slack_bots WHERE team_id = %s" if db_type == 'postgres' else "SELECT bot_token FROM slack_bots WHERE team_id = ?"
            cursor.execute(query, (team_id,))
            result = cursor.fetchone()
            if not result:
                return f"Error: No bot token found for team_id {team_id}"
            slack_token = result[0]
        except Exception as e:
            return f"Error fetching Slack token: {str(e)}"
        finally:
            conn.close()

        try:
            from slack_sdk.web.async_client import AsyncWebClient
            client = AsyncWebClient(token=slack_token)
            await client.chat_postMessage(channel=user_id, text=message)
            return "Message sent successfully to Slack"
        except Exception as e:
            return f"Error sending message to Slack: {str(e)}"
            
    else:
        # Default to Telegram
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            return "Error: TELEGRAM_BOT_TOKEN not found"
            
        try:
            bot = Bot(token=token)
            await bot.send_message(chat_id=user_id, text=message)
            await bot.send_chat_action(chat_id=user_id, action="typing")
            return "Message sent successfully to Telegram"
        except Exception as e:
            return f"Error sending message to Telegram: {str(e)}"
