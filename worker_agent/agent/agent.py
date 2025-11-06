import litellm
from worker_agent.directory.directory import Directory
import json
from worker_agent.agent.prompt import get_system_prompt
from dotenv import load_dotenv
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from worker_agent.agent.tools import set_time_event, delete_time_event, get_mcp_client_manager
load_dotenv()

class WorkerAgent:
    def __init__(self, db_path=None):
        """Initialize the WorkerAgent with a Directory object and LiteLLM client."""
        # Default to parent directory for local development
        if db_path is None:
            # Go up three levels from agent.py -> agent/ -> worker_agent/ -> alpha-v0.1/ -> Donna/
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'chats.db')
        self.directory = Directory(db_path=db_path)
        # LiteLLM reads OPENAI_API_KEY from environment variables automatically
        
        # Store agent_name and user_id for current session
        self.agent_name = None
        self.user_id = None
        
        # Initialize MCP client manager for Brave Search
        try:
            self.mcp_manager = get_mcp_client_manager()
        except ValueError as e:
            print(f"Warning: MCP client not available: {e}")
            self.mcp_manager = None
        
        # Initialize tools and tool functions
        self.tools = self._get_tools()
        self.tool_functions = {
            "set_time_event": set_time_event,
            "delete_time_event": delete_time_event
        }
        # Add MCP tools to tool_functions dynamically
        if self.mcp_manager:
            try:
                mcp_tools = self.mcp_manager.get_tools()
                for tool in mcp_tools:
                    # Create a wrapper function for each MCP tool
                    self.tool_functions[tool.name] = self._create_mcp_tool_wrapper(tool.name)
            except Exception as e:
                print(f"Warning: Could not load MCP tools: {e}")
    
    def _get_tools(self):
        """Define and return the tools array for the worker agent (local + MCP tools)."""
        tools = []
        
        # Add MCP tools (Brave Search, etc.)
        if self.mcp_manager:
            try:
                mcp_tools = self.mcp_manager.get_tools()
                for tool in mcp_tools:
                    # Convert MCP tool format to LiteLLM format
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.inputSchema  # Already in JSON Schema format
                        }
                    })
            except Exception as e:
                print(f"Warning: Could not load MCP tools: {e}")
        
        # Add local tools (time events)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "set_time_event",
                    "description": "Set a time-based event/reminder. Use this to schedule reminders or recurring tasks. Use IST Timezone for the next trigger timestamp.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "next_trigger_timestamp": {
                                "type": "string",
                                "description": "Next trigger time in ISO format (e.g., 2025-10-28T14:30:00). Use IST Timezone for the next trigger timestamp."
                            },
                            "is_recurring": {
                                "type": "boolean",
                                "description": "Whether this is a recurring event"
                            },
                            "freq": {
                                "type": "string",
                                "description": "Frequency: YEARLY, MONTHLY, WEEKLY, DAILY, HOURLY, MINUTELY, SECONDLY (optional if is_recurring is True)",
                                "enum": ["YEARLY", "MONTHLY", "WEEKLY", "DAILY", "HOURLY", "MINUTELY", "SECONDLY"]
                            },
                            "interval": {
                                "type": "integer",
                                "description": "Interval between occurrences (optional, e.g., 2 for every other day)"
                            },
                            "until": {
                                "type": "string",
                                "description": "End date in ISO format (optional)"
                            },
                            "count": {
                                "type": "integer",
                                "description": "Number of occurrences (optional)"
                            },
                            "byweekday": {
                                "type": "string",
                                "description": "Days of week as comma-separated values: MO,TU,WE,TH,FR,SA,SU (optional)"
                            },
                            "bymonthday": {
                                "type": "integer",
                                "description": "Day of month 1-31 (optional)"
                            },
                            "bymonth": {
                                "type": "integer",
                                "description": "Month 1-12 (optional)"
                            },
                            "reminder_name": {
                                "type": "string",
                                "description": "Unique name for this reminder"
                            },
                            "message": {
                                "type": "string",
                                "description": "Message to send when this event is triggered"
                            }
                        },
                        "required": ["next_trigger_timestamp", "is_recurring", "reminder_name"]
                    }
                }
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "delete_time_event",
                    "description": "Delete a time-based event/reminder by its name.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reminder_name": {
                                "type": "string",
                                "description": "Name of the reminder to delete"
                            }
                        },
                        "required": ["reminder_name"]
                    }
                }
            }
        )
        
        return tools
    
    def _create_mcp_tool_wrapper(self, tool_name):
        """Create a wrapper function for an MCP tool."""
        def mcp_tool_wrapper(**arguments):
            if self.mcp_manager:
                result = self.mcp_manager.call_tool(tool_name, arguments)
                # Result is now a string from fastmcp
                return result
            else:
                return "MCP client not available"
        return mcp_tool_wrapper

    def invoke(self, agent_name, user_id, message, medium="", timestamp=None):
        """Invoke the worker agent with a message."""
        # Store current session info
        self.agent_name = agent_name
        self.user_id = user_id
        
        # Use UTC timezone-aware datetime if no timestamp provided
        timestamp = timestamp or datetime.now(ZoneInfo("UTC"))
        
        # Create and store user message
        user_message = self._create_user_message(message, medium, timestamp)
        self.directory.add_context(agent_name, user_id, user_message)
        
        # Prepare messages for LLM
        messages = self._prepare_messages(agent_name, user_id)
        
        # Run ReAct loop and get final response
        assistant_message = self._react_loop(messages, agent_name, user_id)
        
        # Store and return assistant response
        self.directory.add_context(agent_name, user_id, assistant_message)
        return assistant_message
    
    def _create_user_message(self, message, medium, timestamp):
        """Create a formatted user message with date, time, and medium."""
        # Convert to IST (Indian Standard Time)
        ist_timezone = ZoneInfo("Asia/Kolkata")
        if timestamp.tzinfo is None:
            # If timestamp is naive, assume it's UTC
            timestamp = timestamp.replace(tzinfo=ZoneInfo("UTC"))
        ist_timestamp = timestamp.astimezone(ist_timezone)
        
        # Get day and date components
        day_name = ist_timestamp.strftime("%A")
        day = ist_timestamp.day
        month = ist_timestamp.strftime("%b")
        year = ist_timestamp.year
        
        # Get proper ordinal suffix
        if 10 <= day % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        
        date_str = f"{day_name}, {day}{suffix} {month} {year}"
        time_str = ist_timestamp.strftime("%H:%M")
        
        return {
            "role": "user",
            "content": f"Date: {date_str}\nTime: {time_str}\nFROM: {medium}\nMessage: {message}"
        }
    
    def _prepare_messages(self, agent_name, user_id):
        """Prepare messages array for LLM from context."""
        # Get context from directory - it's already in LiteLLM format!
        context_blob = self.directory.get_context(agent_name, user_id)
        messages = json.loads(context_blob) if context_blob else []
        
        # Add system prompt with dynamic active time events section
        system_prompt = get_system_prompt(agent_name, user_id)

        # print(system_prompt)
        if system_prompt:
            messages.insert(0, {
                "role": "system",
                "content": system_prompt
            })
        
        return messages
    
    def _react_loop(self, messages, agent_name, user_id):
        """Run ReAct loop until we get a normal response (no tool calls)."""
        while True:
            # Call LLM with tools
            response = litellm.completion(
                model="deepseek/deepseek-chat",
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
                fallbacks=["together_ai/deepseek-ai/DeepSeek-V3"],  # Fallback to Together AI if primary fails
                timeout=30,
                num_retries=2
            )
            
            assistant_msg = response.choices[0].message
            
            # Check if the model wants to call tools
            if assistant_msg.tool_calls:
                # Prepare tool call request
                tool_call_request = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in assistant_msg.tool_calls
                    ]
                }
                
                # Execute tool calls and collect responses
                tool_responses = []
                for tool_call in assistant_msg.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    # Inject agent_name and user_id for tools that need them
                    if function_name in ["set_time_event", "delete_time_event"]:
                        function_args["agent_name"] = agent_name
                        function_args["user_id"] = user_id
                    
                    # Execute the tool function
                    if function_name in self.tool_functions:
                        tool_result = self.tool_functions[function_name](**function_args)
                    else:
                        tool_result = f"Error: Tool '{function_name}' not found"
                    
                    # Prepare tool response - always add response for every tool call
                    # Convert tool_result to string if it's not already
                    if isinstance(tool_result, str):
                        content = tool_result
                    else:
                        content = json.dumps(tool_result)
                    
                    tool_response = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": content
                    }
                    tool_responses.append(tool_response)
                
                # Store tool call request and all responses atomically
                all_tool_messages = [tool_call_request] + tool_responses
                self.directory.add_context(agent_name, user_id, all_tool_messages)
                
                # Add to messages for current conversation
                messages.append(assistant_msg)
                messages.extend(tool_responses)
                continue
            else:
                # No tool calls, return the final response (LiteLLM format)
                return {
                    "role": "assistant",
                    "content": assistant_msg.content
                }
    


