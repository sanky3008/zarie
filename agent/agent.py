import litellm
from agent.state.state import State
import json
from agent.prompt import get_system_prompt
from dotenv import load_dotenv
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from agent.tools import invoke_worker_agent, get_mcp_client_manager
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
        
        # Initialize MCP client manager for Brave Search
        try:
            self.mcp_manager = get_mcp_client_manager()
        except ValueError as e:
            print(f"Warning: MCP client not available: {e}")
            self.mcp_manager = None
        
        # Initialize tools and tool functions
        self.tools = self._get_tools()
        self.tool_functions = {
            "invoke_worker_agent": invoke_worker_agent
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
        """Define and return the tools array for the agent (local + MCP tools)."""
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
        
        # Add local tools
        tools.append({
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
        })
        
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

    def invoke(self, user_id, message, medium, timestamp=None):
        """Invoke the agent with a user message and medium."""
        # Use UTC timezone-aware datetime if no timestamp provided
        timestamp = timestamp or datetime.now(ZoneInfo("UTC"))
        
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
        
        # Add system prompt with dynamic worker agents section
        system_prompt = get_system_prompt(user_id)

        # print(system_prompt)
        if system_prompt:
            messages.insert(0, {
                "role": "system",
                "content": system_prompt
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
                    
                    # Inject user_id for tools that need it
                    if function_name == "invoke_worker_agent":
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
    

