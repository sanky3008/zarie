from pickle import TRUE
import litellm
from worker_agent.directory.directory import Directory
import json
from worker_agent.agent.prompt import get_system_prompt
from dotenv import load_dotenv
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from worker_agent.agent.tools import set_time_event, delete_time_event, get_mcp_client_manager, gmail_read_emails, calendar_get_events, calendar_create_event
load_dotenv()

# Enable LiteLLM detailed debugging
if os.getenv("LITELLM_DEBUG").lower() == "true":
    litellm._turn_on_debug()

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
        
        # Tools will be initialized lazily on first use
        self.tools = None
        self.tools_initialized = False
        self.tool_functions = {
            "set_time_event": set_time_event,
            "delete_time_event": delete_time_event,
            "gmail_read_emails": gmail_read_emails,
            "calendar_get_events": calendar_get_events,
            "calendar_create_event": calendar_create_event
        }
    
    async def _ensure_tools_initialized(self):
        """Ensure tools are initialized (lazy initialization)."""
        if self.tools_initialized:
            return
        
        self.tools = await self._get_tools()
        self.tools_initialized = True
    
    async def _get_tools(self):
        """Define and return the tools array for the worker agent (local + MCP tools)."""
        tools = []
        
        # Add MCP tools (Brave Search, etc.)
        if self.mcp_manager:
            try:
                mcp_tools = await self.mcp_manager.get_tools()
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
                    # Add async tool wrapper
                    self.tool_functions[tool.name] = self._create_mcp_tool_wrapper(tool.name)
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

        # Add Google Calendar & Gmail tools
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "gmail_read_emails",
                    "description": "Read recent emails from the user's Gmail. Requires user to have connected their Google account.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "count": {
                                "type": "integer",
                                "description": "Number of emails to retrieve (default 5)"
                            },
                            "query": {
                                "type": "string",
                                "description": "Gmail search query (e.g., 'is:unread', 'from:boss@company.com', 'subject:meeting')"
                            }
                        },
                        "required": []
                    }
                }
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "calendar_get_events",
                    "description": "Get upcoming calendar events from the user's Google Calendar. Requires user to have connected their Google account.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "count": {
                                "type": "integer",
                                "description": "Maximum number of events to return (default 5)"
                            },
                            "time_min": {
                                "type": "string",
                                "description": "Start time in ISO format to fetch events from (default: now)"
                            }
                        },
                        "required": []
                    }
                }
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "calendar_create_event",
                    "description": "Create a new event on the user's primary Google Calendar. Requires user to have connected their Google account.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "string",
                                "description": "Title of the event"
                            },
                            "start_time": {
                                "type": "string",
                                "description": "Start time in ISO format (e.g., 2025-01-15T14:00:00+05:30)"
                            },
                            "end_time": {
                                "type": "string",
                                "description": "End time in ISO format (e.g., 2025-01-15T15:00:00+05:30)"
                            },
                            "description": {
                                "type": "string",
                                "description": "Optional description for the event"
                            },
                            "attendees": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional list of email addresses to invite as attendees"
                            }
                        },
                        "required": ["summary", "start_time", "end_time"]
                    }
                }
            }
        )

        return tools
    
    def _create_mcp_tool_wrapper(self, tool_name):
        """Create an async wrapper function for an MCP tool."""
        async def mcp_tool_wrapper(**arguments):
            if self.mcp_manager:
                result = await self.mcp_manager.call_tool(tool_name, arguments)
                # Result is now a string from fastmcp
                return result
            else:
                return "MCP client not available"
        return mcp_tool_wrapper

    async def invoke(self, agent_name, user_id, message, medium="", timestamp=None, user_timezone='Asia/Kolkata'):
        """Invoke the worker agent with a message."""
        # Ensure tools are initialized
        await self._ensure_tools_initialized()
        
        # Store current session info - REMOVED to fix race condition (stateless)
        # self.agent_name = agent_name
        # self.user_id = user_id
        
        # Use UTC timezone-aware datetime if no timestamp provided
        timestamp = timestamp or datetime.now(ZoneInfo("UTC"))
        
        # Create and store user message
        user_message = self._create_user_message(message, medium, timestamp, user_timezone)
        self.directory.add_context(agent_name, user_id, user_message)
        
        # Prepare messages for LLM
        messages = await self._prepare_messages(agent_name, user_id)
        
        # Run ReAct loop and get final response
        assistant_message = await self._react_loop(messages, agent_name, user_id, user_timezone)
        
        # Store and return assistant response
        self.directory.add_context(agent_name, user_id, assistant_message)
        return assistant_message
    
    def _create_user_message(self, message, medium, timestamp, user_timezone):
        """Create a formatted user message with date, time, and medium."""
        # Convert to User Timezone
        try:
            tz = ZoneInfo(user_timezone)
        except Exception:
            tz = ZoneInfo("Asia/Kolkata")
            
        if timestamp.tzinfo is None:
            # If timestamp is naive, assume it's UTC
            timestamp = timestamp.replace(tzinfo=ZoneInfo("UTC"))
        local_timestamp = timestamp.astimezone(tz)
        
        # Get day and date components
        day_name = local_timestamp.strftime("%A")
        day = local_timestamp.day
        month = local_timestamp.strftime("%b")
        year = local_timestamp.year
        
        # Get proper ordinal suffix
        if 10 <= day % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        
        date_str = f"{day_name}, {day}{suffix} {month} {year}"
        time_str = local_timestamp.strftime("%H:%M")
        
        return {
            "role": "user",
            "content": f"Date: {date_str}\nTime: {time_str}\nTimezone: {user_timezone}\nFROM: {medium}\nMessage: {message}"
        }
    
    async def _prepare_messages(self, agent_name, user_id):
        """Prepare messages array for LLM from context."""
        # Get context from directory - it's already in LiteLLM format!
        context_blob = self.directory.get_context(agent_name, user_id)
        messages = json.loads(context_blob) if context_blob else []
        
        # Helper to find user message indices
        user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        
        # Split logic: keep everything AFTER the 5th last user message as "recent"
        split_index = 0
        if len(user_indices) >= 5:
             # If we want 5 recent user messages:
             # user_indices[-5] is the index of the 5th message from the end
             split_index = user_indices[-5]
        
        old_messages = messages[:split_index]
        recent_messages = messages[split_index:]
        
        # Check for summarization trigger
        running_summary = self.directory.get_running_summary(agent_name, user_id)
        
        summaisation_length = 100
        if len(messages) > summaisation_length:
             # We want to summarise the "old" part to keep the context window manageable.
             # Let's say we keep the last 25 user messages always available as "raw" context.
             # So we summarise everything before that.
             if split_index > 0:
                 from worker_agent.agent.summarisation import summarise_context
                 new_summary = await summarise_context(self.directory, agent_name, user_id, old_messages)
                 if new_summary:
                     running_summary = new_summary
                     # Clear old_messages as they are now summarised
                     # Note: summarise_context marks them as summarised in DB, so subsequent calls won't fetch them.
                     # But for THIS call, we need to remove them from prompt.
                     # recent_messages are what remains.
                     pass 
        
        # Add system prompt with dynamic active time events section
        system_prompt = get_system_prompt(agent_name, user_id)
        
        # Inject running summary if exists
        if running_summary:
            system_prompt += f"\n\n4. **Worker Agent Context Summary (OPERATIONAL)**\n<worker_context_summary>\n{running_summary}\n</worker_context_summary>"

        # print(system_prompt)
        final_messages = []
        if system_prompt:
            final_messages.append({
                "role": "system",
                "content": system_prompt
            })
        
        if len(messages) > summaisation_length and split_index > 0:
            final_messages.extend(recent_messages)
        else:
            final_messages.extend(messages)
        
        return final_messages
    
    async def _react_loop(self, messages, agent_name, user_id, user_timezone='Asia/Kolkata'):
        """Run ReAct loop until we get a normal response (no tool calls)."""
        while True:
            # Call LLM with tools using async completion
            response = await litellm.acompletion(
                model="deepinfra/deepseek-ai/DeepSeek-V3.2",
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
                # fallbacks=["together_ai/deepseek-ai/DeepSeek-V3"],  # Removed per user request
                timeout=30,
                num_retries=2,
                temperature=0.6,
                top_p=0.95
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
                        function_args["user_timezone"] = user_timezone
                    elif function_name in ["gmail_read_emails", "calendar_get_events", "calendar_create_event"]:
                        function_args["user_id"] = user_id
                    
                    # Execute the tool function (handle both sync and async)
                    if function_name in self.tool_functions:
                        tool_func = self.tool_functions[function_name]
                        # Check if it's async
                        import asyncio
                        if asyncio.iscoroutinefunction(tool_func):
                            tool_result = await tool_func(**function_args)
                        else:
                            tool_result = tool_func(**function_args)
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
    


