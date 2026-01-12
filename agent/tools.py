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


async def invoke_worker_agent(agent_name: str, user_id: str, purpose: str, message: str, user_timezone: str = 'Asia/Kolkata', timestamp=None):
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
        timestamp (datetime): (Optional) Timestamp for the interaction.
        
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
        user_timezone=user_timezone,
        timestamp=timestamp
    )
    
    content = response.get('content', 'No response from worker agent')
    return content.replace('**', '') if isinstance(content, str) else content


async def send_message_to_user(user_id: str, message: str, thread_ts: str = None, is_mpim: bool = False):
    """
    Send a message to the user immediately.
    
    Use this tool to provide updates to the user when a task is taking time or to keep them informed
    without waiting for the final response. This does NOT break the agent's thought process loop.
    
    Args:
        user_id (str): The user's ID (Telegram ID or Slack User/Channel ID, injected automatically).
        message (str): The message content to send to the user.
        thread_ts (str): Thread timestamp for replying in a thread (MPIM only, injected automatically).
        is_mpim (bool): Whether this is a Multi-Party DM (injected automatically).
        
    Returns:
        str: Status of the message sending.
    """
    from user_manager import get_user
    
    # Get user platform
    user = get_user(user_id)
    platform = user.get('platform', 'telegram') if user else 'telegram'
    
    if not message or not message.strip():
        return "Error: Message is empty"
    
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
            
            # For MPIM, always reply in thread if thread_ts is provided
            if is_mpim and thread_ts:
                await client.chat_postMessage(channel=user_id, text=message, thread_ts=thread_ts)
            else:
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


def generate_google_auth_link(user_id: str):
    """
    Generate a link for the user to connect their Google account.

    Args:
        user_id (str): The user's ID (injected automatically).
    Returns:
        str: The authorization URL.
    """
    try:
        from google_oauth_handler import get_authorization_url
        return get_authorization_url(user_id)
    except Exception as e:
        return f"Error generating link: {str(e)}"


def calendar_get_events(user_id: str, count: int = 5, time_min: str = None):
    """
    Get upcoming calendar events.
    
    Args:
        user_id (str): User ID.
        count (int): Max events.
        time_min (str): Start time in ISO format (default: now).
    Returns:
        str: List of events.
    """
    from google_oauth_handler import get_google_service
    import datetime
    
    service = get_google_service(user_id, 'calendar', 'v3')
    if not service:
        return "Error: Could not authenticate with Google."
        
    try:
        now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
        t_min = time_min if time_min else now
        
        events_result = service.events().list(calendarId='primary', timeMin=t_min,
                                              maxResults=count, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])
        
        if not events:
            return "No upcoming events found."
            
        output = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', '(No Title)')
            output.append(f"- {start}: {summary}")
            
        return "\n".join(output)
    except Exception as e:
        return f"Error getting events: {str(e)}"


def calendar_create_event(user_id: str, summary: str, start_time: str, end_time: str, description: str = None, attendees: list = None):
    """
    Create a new event on the user's primary calendar.
    
    Args:
        user_id (str): User ID.
        summary (str): Title of event.
        start_time (str): ISO format start time.
        end_time (str): ISO format end time.
        description (str): Optional description.
        attendees (list): Optional list of email strings for participants.
    Returns:
        str: Confirmation.
    """
    from google_oauth_handler import get_google_service
    service = get_google_service(user_id, 'calendar', 'v3')
    if not service:
        return "Error: Could not authenticate with Google."
        
    try:
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time,
                'timeZone': 'UTC', # Assuming input is UTC ISO or offset aware
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'UTC',
            },
        }
        
        if attendees:
            event['attendees'] = [{'email': email} for email in attendees]
            
        event_result = service.events().insert(calendarId='primary', body=event).execute()
        return f"Event created: {event_result.get('htmlLink')}"
    except Exception as e:
        return f"Error creating event: {str(e)}"
