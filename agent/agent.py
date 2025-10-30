import litellm
from state.state import State
import json
from agent.prompt import SYSTEM_PROMPT
from dotenv import load_dotenv
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from agent.tools import web_search, invoke_worker_agent
load_dotenv()

class Agent:
    def __init__(self, db_path=None):
        """Initialize the Agent with a State object and LiteLLM client."""
        # Default to parent directory for local development
        if db_path is None:
            # Go up two levels from agent.py -> agent/ -> alpha-v0.1/ -> Donna/
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'chats.db')
        self.state = State(db_path=db_path)
        # LiteLLM reads OPENAI_API_KEY from environment variables automatically
        
        # Initialize tools and tool functions
        self.tools = self._get_tools()
        self.tool_functions = {
            "web_search": web_search,
            "invoke_worker_agent": invoke_worker_agent
        }
    
    def _get_tools(self):
        """Define and return the tools array for the agent."""
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
                    "name": "invoke_worker_agent",
                    "description": "Create or invoke a worker agent to handle automated workflows, reminders, and recurring tasks. Use this when the user asks to set up reminders, schedule events, or needs automated task management. Each worker agent maintains its own context and can use tools like web search and time event management.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "agent_name": {
                                "type": "string",
                                "description": "Unique name for the worker agent (e.g., 'reminder_agent', 'cricket_tracker', 'task_manager'). Use descriptive names that reflect the agent's purpose."
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Brief description of what this agent is responsible for (e.g., 'Handle weekly reminders', 'Track cricket scores', 'Manage daily tasks')"
                            },
                            "message": {
                                "type": "string",
                                "description": "The instruction or task to give to the worker agent"
                            }
                        },
                        "required": ["agent_name", "purpose", "message"]
                    }
                }
            }
        ]

    def invoke(self, user_id, message, medium, timestamp=None):
        """Invoke the agent with a user message and medium."""
        timestamp = timestamp or datetime.now()
        
        # Create and store user message
        user_message = self._create_user_message(message, medium, timestamp)
        self.state.add_context(user_id, user_message)
        
        # Prepare messages for LLM
        messages = self._prepare_messages(user_id)
        
        # Run ReAct loop and get final response
        assistant_message = self._react_loop(messages, user_id)
        
        # Store and return assistant response
        self.state.add_context(user_id, assistant_message)
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
    
    def _prepare_messages(self, user_id):
        """Prepare messages array for LLM from context."""
        # Get context from state - it's already in LiteLLM format!
        context_blob = self.state.get_context(user_id)
        messages = json.loads(context_blob) if context_blob else []
        
        # Add system prompt if available
        if SYSTEM_PROMPT:
            messages.insert(0, {
                "role": "system",
                "content": SYSTEM_PROMPT
            })
        
        return messages
    
    def _react_loop(self, messages, user_id):
        """Run ReAct loop until we get a normal response (no tool calls)."""
        while True:
            # Call LLM with tools
            # print(messages)
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
                    
                    # Inject user_id for tools that need it
                    if function_name == "invoke_worker_agent":
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
                self.state.add_context(user_id, all_tool_messages)
                
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
    

