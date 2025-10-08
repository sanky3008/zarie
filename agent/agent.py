import litellm
from state.state import State
import json
from agent.prompt import SYSTEM_PROMPT
from dotenv import load_dotenv
import os
from datetime import datetime
from agent.tools import web_search
load_dotenv()

class Agent:
    def __init__(self, db_path='chats.db'):
        """Initialize the Agent with a State object and LiteLLM client."""
        self.state = State(db_path=db_path)
        # LiteLLM reads OPENAI_API_KEY from environment variables automatically
        
        # Initialize tools and tool functions
        self.tools = self._get_tools()
        self.tool_functions = {
            "web_search": web_search
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
        date_str = timestamp.strftime("%dth %b %Y")
        time_str = timestamp.strftime("%H:%M")
        
        return {
            "type": "message",
            "role": "user",
            "content": f"Date: {date_str}, Time: {time_str}, Medium: {medium}\nMessage: {message}"
        }
    
    def _prepare_messages(self, user_id):
        """Prepare messages array for LLM from context."""
        # Get context from state
        context_blob = self.state.get_context(user_id)
        context = json.loads(context_blob) if context_blob else []
        
        # Convert context to LiteLLM messages format
        messages = []
        for item in context:
            if item.get("type") == "message":
                messages.append({
                    "role": item["role"],
                    "content": item["content"]
                })
        
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
            response = litellm.completion(
                model="deepseek/deepseek-chat",
                messages=messages,
                tools=self.tools,
                tool_choice="auto"
            )
            
            assistant_msg = response.choices[0].message
            
            # Check if the model wants to call tools
            if assistant_msg.tool_calls:
                # Store tool call request in context
                tool_call_request = {
                    "type": "tool_call_request",
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in assistant_msg.tool_calls
                    ]
                }
                self.state.add_context(user_id, tool_call_request)
                
                # Process tool calls and add results to messages
                messages.append(assistant_msg)
                self._execute_tool_calls(assistant_msg.tool_calls, messages, user_id)
                continue
            else:
                # No tool calls, return the final response
                return {
                    "type": "message",
                    "role": "assistant",
                    "content": assistant_msg.content
                }
    
    def _execute_tool_calls(self, tool_calls, messages, user_id):
        """Execute tool calls and add results to messages array."""
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            # Execute the tool function
            if function_name in self.tool_functions:
                tool_result = self.tool_functions[function_name](**function_args)
                
                # Store tool call response in context
                tool_call_response = {
                    "type": "tool_call_response",
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": tool_result
                }
                self.state.add_context(user_id, tool_call_response)
                
                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": json.dumps(tool_result)
                })

