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

from agent.tools import (
    invoke_worker_agent, get_mcp_client_manager, send_message_to_user,
    generate_google_auth_link, gmail_read_emails, calendar_get_events, calendar_create_event
)

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
            "send_message_to_user": send_message_to_user,
            "generate_google_auth_link": generate_google_auth_link,
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
        
        tools.append({
            "type": "function",
            "function": {
                "name": "generate_google_auth_link",
                "description": "Generate a link for the user to connect their Google account. Use this when user asks to connect or link Gmail/Calendar.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "gmail_read_emails",
                "description": "Read recent emails from the user's Gmail.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "count": { "type": "integer", "description": "Number of emails (default 5)" },
                        "query": { "type": "string", "description": "Gmail search query (e.g. 'is:unread')" }
                    },
                    "required": []
                }
            }
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "calendar_get_events",
                "description": "Get upcoming calendar events.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "count": { "type": "integer", "description": "Max events" },
                        "time_min": { "type": "string", "description": "Start time ISO (default now)" }
                    },
                    "required": []
                }
            }
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "calendar_create_event",
                "description": "Create a new event on the user's primary calendar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": { "type": "string", "description": "Title of event" },
                        "start_time": { "type": "string", "description": "Start time (ISO format)" },
                        "end_time": { "type": "string", "description": "End time (ISO format)" },
                        "description": { "type": "string", "description": "Event description" },
                        "attendees": { 
                            "type": "array", 
                            "items": { "type": "string" },
                            "description": "List of email addresses of attendees"
                        }
                    },
                    "required": ["summary", "start_time", "end_time"]
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

    async def invoke(self, user_id, message, medium, timestamp=None, user_timezone='Asia/Kolkata',
                     is_mpim=False, thread_ts=None, author_name=None, author_id=None, reply_ts=None):
        """Invoke the agent with a user message and medium - streaming generator.
        
        Args:
            user_id: User ID (or MPIM channel ID for group DMs)
            message: The user's message text
            medium: Source of the message (e.g., "End-User via Slack")
            timestamp: Message timestamp (UTC)
            user_timezone: User's timezone string
            is_mpim: True if this is a Multi-Party DM
            thread_ts: Thread timestamp if message is a reply (MPIM only, for context)
            author_name: Display name of message author (MPIM only)
            author_id: Slack User ID of message author (MPIM only)
            reply_ts: Timestamp to reply to (MPIM only, for tools)
        """
        # Ensure tools are initialized
        await self._ensure_tools_initialized()
        
        # Use UTC timezone-aware datetime if no timestamp provided
        timestamp = timestamp or datetime.now(ZoneInfo("UTC"))
        
        # 1. Create and Store User Message
        user_message_obj = self._create_user_message(
            message=message, 
            medium=medium, 
            timestamp=timestamp, 
            user_timezone=user_timezone,
            author_name=author_name if is_mpim else None,
            author_id=author_id if is_mpim else None
        )
        
        # For MPIM/Thread: we persist thread_ts
        # For DM: thread_ts is None
        self.state.add_context(
            user_id, 
            user_message_obj, 
            thread_ts=thread_ts,
            author_name=author_name if is_mpim else None,
            author_id=author_id if is_mpim else None
        )
        
        # 2. Prepare Context (Read from DB)
        messages = await self._prepare_messages(user_id, user_timezone, thread_ts=thread_ts)
        
        # Stream responses from ReAct loop
        import asyncio
        async for chunk in self._react_loop_streaming(
            messages, 
            user_id, 
            user_timezone, 
            timestamp=timestamp,
            is_mpim=is_mpim,
            thread_ts=thread_ts,
            reply_ts=reply_ts
        ):
            yield chunk
            await asyncio.sleep(0.5)  # 500ms delay between chunks for natural pacing
    
    def _create_user_message(self, message, medium, timestamp, user_timezone, author_name=None, author_id=None):
        """Create a formatted user message with date, time, and medium."""
        from agent.utils import TimezoneUtils
        
        timestamp_str = TimezoneUtils.format_timestamp(timestamp, user_timezone)
        
        # Construct header
        header = f"{timestamp_str}\nFROM: {medium}"
        if author_name:
             if author_id:
                 header += f"\nAuthor: {author_name} | <@{author_id}>"
             else:
                 header += f"\nAuthor: {author_name}"
             
        return {
            "role": "user",
            "content": f"{header}\nMessage: {message}"
        }
    
    async def _prepare_messages(self, user_id, user_timezone='Asia/Kolkata', thread_ts=None):
        """Prepare messages array for LLM from context."""
        
        # 1. Fetch Active Messages (Recent context)
        # If thread_ts is present, we are in a thread. Fetch the thread conversation.
        # If thread_ts is None, we are in root. Fetch the root conversation.
        active_messages = self.state.get_messages(user_id, thread_ts=thread_ts, exclude_summarised=True)
        
        # 2. Logic for Summarization and Background History
        # We only summarize ROOT messages. Thread messages are usually short-lived contexts or depend on root.
        # However, if we are in a thread, we might want to inject ROOT history as background context.
        
        background_context_str = ""
        running_summary = self.state.get_running_summary(user_id)

        if thread_ts:
            # --- THREAD MODE ---
            # Active messages are the thread itself.
            # Background context should be recent ROOT messages (to give context about the channel).
            
            # Fetch recent root messages (limit 20)
            root_messages = self.state.get_messages(user_id, thread_ts=None, limit=20, exclude_summarised=True)
            # Filter out the parent message if it appears in root_messages (it's already in active_messages as cached in thread)
            # Actually get_messages(thread_ts=...) includes the parent if slack_ts matches.
            pass 
            
            if root_messages:
                 formatted_root = self._format_conversation_history(root_messages, user_timezone)
                 background_context_str = f"\n\n## Recent Channel Activity (Background Context)\n<conversation_history>\n{formatted_root}\n</conversation_history>"
                 
        else:
            # --- ROOT MODE (Standard DM) ---
            # Check for summarization on active messages
            # Only summarize if we have a lot of messages
            if len(active_messages) > 100: # Threshold
                 user_indices = [i for i, m in enumerate(active_messages) if m.get("role") == "user"]
                 if len(user_indices) >= 10:
                     # Summarize older half
                     split_idx = user_indices[-6] # Keep last 6 interactions
                     to_summarise = active_messages[:split_idx]
                     active_messages = active_messages[split_idx:]
                     
                     from agent.summarisation import summarise_context
                     # Summarize
                     new_summary = await summarise_context(self.state, user_id, to_summarise)
                     if new_summary:
                        running_summary = new_summary

        # 3. Construct System Prompt
        system_prompt = get_system_prompt(user_id)
        
        if running_summary:
            system_prompt += f"\n\n## User Context Summary (PERSONALIZATION REFERENCE)\n<conversation_summary>\n{running_summary}\n</conversation_summary>"
        
        if background_context_str:
            system_prompt += background_context_str
            
        final_messages = []
        if system_prompt:
             final_messages.append({
                "role": "system",
                "content": system_prompt
            })
            
        # 4. Append Active Messages
        # We need to make sure they are in LiteLLM format (role, content, tool_calls, etc)
        # s.state.get_messages returns dicts that are mostly compatible, but we need to ensure cleanliness.
        
        for msg in active_messages:
            # Filter out internal keys like 'thread_ts', 'slack_ts', 'author_id' that LiteLLM doesn't need
            clean_msg = {
                "role": msg['role'],
                "content": msg['content']
            }
            if msg.get('tool_calls'):
                clean_msg['tool_calls'] = msg['tool_calls']
            if msg.get('tool_call_id'):
                 clean_msg['tool_call_id'] = msg['tool_call_id']
            if msg.get('tool_name'):
                 clean_msg['name'] = msg['tool_name'] # LiteLLM expects 'name' for tool response
                 
            final_messages.append(clean_msg)
            
        return final_messages

    def _format_conversation_history(self, messages, user_timezone='Asia/Kolkata'):
        """Format conversation history into a structured string."""
        formatted_lines = []
        try:
            target_tz = ZoneInfo(user_timezone)
        except Exception:
            target_tz = ZoneInfo("Asia/Kolkata")
        
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
                
                # Convert to Target Timezone
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                local_dt = dt.astimezone(target_tz)
                timestamp_str = local_dt.strftime("%b %d, %I:%M %p")
            
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
    
    async def _react_loop_streaming(self, messages, user_id, user_timezone='Asia/Kolkata', 
                                  timestamp=None, is_mpim=False, thread_ts=None, reply_ts=None):
        """Run ReAct loop, yielding text chunks on \\n\\n boundaries and executing tool calls."""
        while True:
            # DEBUG: Save context to file before LLM call
            # try:
            #     import json
            #     def default_serializer(obj):
            #         if hasattr(obj, 'dict'): return obj.dict()
            #         if hasattr(obj, 'to_dict'): return obj.to_dict()
            #         return str(obj)
            #     with open("debug_context.json", "w") as f:
            #         json.dump(messages, f, indent=2, default=default_serializer)
            # except Exception as e:
            #     print(f"DEBUG SAVE FAILED: {e}")

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
                    
                    if function_name == "invoke_worker_agent":
                        function_args["user_id"] = user_id
                        function_args["user_timezone"] = user_timezone
                        if timestamp:
                            function_args["timestamp"] = timestamp
                    elif function_name == "send_message_to_user":
                        function_args["user_id"] = user_id
                        # Inject MPIM thread context if available
                        if is_mpim:
                            function_args["is_mpim"] = True
                            if reply_ts:
                                function_args["thread_ts"] = reply_ts
                            elif thread_ts:
                                function_args["thread_ts"] = thread_ts
                    elif function_name in ["generate_google_auth_link", "gmail_read_emails", "calendar_get_events", "calendar_create_event"]:
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
                thread_ts = getattr(self, '_current_thread_ts', None)
                self.state.add_context(user_id, all_tool_messages, thread_ts=thread_ts)
                
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
                thread_ts = getattr(self, '_current_thread_ts', None)
                self.state.add_context(user_id, {
                    "role": "assistant",
                    "content": content
                }, thread_ts=thread_ts)
                return
    

