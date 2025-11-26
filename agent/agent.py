import litellm
from agent.state.state import State
import json
from agent.prompt import get_system_prompt
from dotenv import load_dotenv
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from agent.tools import invoke_worker_agent, get_mcp_client_manager, send_message_to_user
load_dotenv()

# Enable LiteLLM detailed debugging
if os.getenv("LITELLM_DEBUG").lower() == "true":
    litellm._turn_on_debug()

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
        
        # Tools will be initialized lazily on first use
        self.tools = None
        self.tools_initialized = False
        self.tool_functions = {
            "invoke_worker_agent": invoke_worker_agent,
            "send_message_to_user": send_message_to_user
        }
    
    async def _ensure_tools_initialized(self):
        """Ensure tools are initialized (lazy initialization)."""
        if self.tools_initialized:
            return
        
        self.tools = await self._get_tools()
        self.tools_initialized = True
    
    async def _get_tools(self):
        """Define and return the tools array for the agent (local + MCP tools)."""
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
        
        tools.append({
            "type": "function",
            "function": {
                "name": "send_message_to_user",
                "description": "Send a message to the user immediately. Use this to provide updates when a task is taking time or to keep the user informed without waiting for the final response. This does NOT break the agent's thought process loop. Always use before searching or calling any tools that take time.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message content to send to the user."
                        }
                    },
                    "required": ["message"]
                }
            }
        })
        
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

    async def invoke(self, user_id, message, medium, timestamp=None):
        """Invoke the agent with a user message and medium - streaming generator."""
        # Ensure tools are initialized
        await self._ensure_tools_initialized()
        
        # Use UTC timezone-aware datetime if no timestamp provided
        timestamp = timestamp or datetime.now(ZoneInfo("UTC"))
        
        # Create and store user message
        user_message = self._create_user_message(message, medium, timestamp)
        self.state.add_context(user_id, user_message)
        
        # Prepare messages for LLM
        messages = self._prepare_messages(user_id)
        
        # Stream responses from ReAct loop
        import asyncio
        async for chunk in self._react_loop_streaming(messages, user_id):
            yield chunk
            await asyncio.sleep(0.5)  # 500ms delay between chunks for natural pacing
    
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
        
        # Format conversation history
        formatted_history = self._format_conversation_history(messages)
        
        # Add conversation history to system prompt 
        if formatted_history:
            system_prompt += f"\n\n<conversation_history>\n{formatted_history}\n</conversation_history>"

        # print(system_prompt)
        if system_prompt:
            # Return a single system message with the complete history
            return [{
                "role": "system",
                "content": system_prompt
            }]
        
        return []

    def _format_conversation_history(self, messages):
        """Format conversation history into a structured string."""
        formatted_lines = []
        ist_timezone = ZoneInfo("Asia/Kolkata")
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            created_at = msg.get("created_at")
            
            # Parse timestamp
            timestamp_str = ""
            if created_at:
                if isinstance(created_at, str):
                    try:
                        dt = datetime.fromisoformat(created_at)
                    except ValueError:
                        dt = datetime.now(ZoneInfo("UTC")) # Fallback
                else:
                    dt = created_at
                
                # Convert to IST
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                ist_dt = dt.astimezone(ist_timezone)
                timestamp_str = ist_dt.strftime("%b %d, %I:%M %p")
            
            if role == "user":
                # Parse user message content
                # Format: Date: ...\nTime: ...\nFROM: <MEDIUM>\nMessage: <CONTENT>
                medium = "User"
                message_text = content
                
                if content and content.startswith("Date:"):
                    lines = content.split('\n')
                    parsed_date = None
                    parsed_time = None
                    
                    for line in lines:
                        if line.startswith("FROM:"):
                            medium = line.replace("FROM:", "").strip()
                        elif line.startswith("Medium:"): # Handle variation
                            medium = line.replace("Medium:", "").strip()
                        elif line.startswith("Message:"):
                            # Everything after "Message:" is the content
                            # We need to handle multi-line messages correctly
                            # Find the index of "Message:" in the original content
                            msg_idx = content.find("Message:")
                            if msg_idx != -1:
                                message_text = content[msg_idx + 8:].strip()
                            break
                        elif line.startswith("Date:"):
                            parsed_date = line.replace("Date:", "").strip()
                        elif line.startswith("Time:"):
                            parsed_time = line.replace("Time:", "").strip()
                    
                    # Handle 2025-11-05 edge case
                    if created_at and (str(created_at).startswith("2025-11-05") or str(created_at).startswith("2025-11-06")):
                         if parsed_date and parsed_time:
                             timestamp_str = f"{parsed_date}, {parsed_time}"

                formatted_lines.append(f"[{medium} ({timestamp_str})]: {message_text}")
            
            elif role == "assistant":
                if msg.get("tool_calls"):
                    for tool_call in msg["tool_calls"]:
                        tool_name = tool_call["function"]["name"]
                        tool_args = tool_call["function"]["arguments"]
                        formatted_lines.append(f"[Zarie Action ({timestamp_str})]: Used tool '{tool_name}' with args {tool_args}")
                elif content:
                    formatted_lines.append(f"[Zarie ({timestamp_str})]: {content}")
            
            elif role == "tool":
                tool_name = msg.get("tool_name")
                if not tool_name:
                    tool_name = "Unknown Tool"
                formatted_lines.append(f"[System Info]: {tool_name} returned: {content}")
        
        return "\n".join(formatted_lines)
    
    async def _react_loop_streaming(self, messages, user_id):
        """Run ReAct loop, yielding text chunks on \\n\\n boundaries and executing tool calls."""
        while True:
            # Call LLM with tools using async completion
            response = await litellm.acompletion(
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
                    elif function_name == "send_message_to_user":
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
                self.state.add_context(user_id, all_tool_messages)
                
                # Add to messages for current conversation
                messages.append(assistant_msg)
                messages.extend(tool_responses)
                continue
            else:
                # No tool calls - stream text response
                content = assistant_msg.content.replace('**', '')
                
                # Yield the full content
                if content.strip():
                    yield content
                
                # Store complete assistant response in state
                self.state.add_context(user_id, {
                    "role": "assistant",
                    "content": content
                })
                return
    

