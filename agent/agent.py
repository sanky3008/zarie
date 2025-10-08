import litellm
from state.state import State
import json
from agent.prompt import SYSTEM_PROMPT
from dotenv import load_dotenv
import os
load_dotenv()

class Agent:
    def __init__(self, db_path='chats.db'):
        """Initialize the Agent with a State object and LiteLLM client."""
        self.state = State(db_path=db_path)
        # LiteLLM reads OPENAI_API_KEY from environment variables automatically

    def invoke(self, user_id, message, medium):
        """Invoke the agent with a user message and medium."""
        # Create a user message object with medium appended to content
        user_message = {
            "type": "message",
            "role": "user",
            "content": f"{message} (medium: {medium})"
        }
        
        # Add the user message to the context
        self.state.add_context(user_id, user_message)
        
        # Get the context
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
        
        # Call LiteLLM completion API
        response = litellm.completion(
            model="deepseek/deepseek-chat",  # Using a standard model name
            messages=messages
        )

        # Extract the assistant message from the response
        assistant_message_content = response.choices[0].message.content
        assistant_message = {
            "type": "message",
            "role": "assistant",
            "content": assistant_message_content
        }
        
        # Add the assistant message to context
        self.state.add_context(user_id, assistant_message)
        
        return assistant_message

