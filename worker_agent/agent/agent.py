import litellm
from worker_agent.directory.directory import Directory
import json
from worker_agent.agent.prompt import SYSTEM_PROMPT
from dotenv import load_dotenv
import os
from datetime import datetime
from worker_agent.agent.tools import web_search, set_time_event, delete_time_event
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
        
        # Initialize tools and tool functions
        self.tools = self._get_tools()
        self.tool_functions = {
            "web_search": web_search,
            "set_time_event": set_time_event,
            "delete_time_event": delete_time_event
        }
    
    def _get_tools(self):
        """Define and return the tools array for the worker agent."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for real-time information. Use this when you need current information, news, facts, or anything that requires up-to-date knowledge from the internet.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query to look up on the web"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
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
            },
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
        ]

    def invoke(self, agent_name, user_id, message, medium="Message_from_Donna", timestamp=None):
        """Invoke the worker agent with a message."""
        # Store current session info
        self.agent_name = agent_name
        self.user_id = user_id
        
        timestamp = timestamp or datetime.now()
        
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
        # System messages don't need date/time formatting
        if medium == "system":
            return {
                "role": "user",
                "content": f"[A time-event has been triggered. Please execute the task and send the response back to Donna.]\nMessage: {message}"
            }
        
        date_str = timestamp.strftime("%dth %b %Y")
        time_str = timestamp.strftime("%H:%M")
        
        return {
            "role": "user",
            "content": f"Date: {date_str}, Time: {time_str}, Medium: {medium}\nMessage: {message}"
        }
    
    def _prepare_messages(self, agent_name, user_id):
        """Prepare messages array for LLM from context."""
        # Get context from directory - it's already in LiteLLM format!
        context_blob = self.directory.get_context(agent_name, user_id)
        messages = json.loads(context_blob) if context_blob else []
        
        # Add system prompt if available
        if SYSTEM_PROMPT:
            messages.insert(0, {
                "role": "system",
                "content": SYSTEM_PROMPT
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
                tool_choice="auto"
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
                        
                        # Prepare tool response
                        tool_response = {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": function_name,
                            "content": json.dumps(tool_result)
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
    


