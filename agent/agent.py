from openai import OpenAI
from state.state import State
import json
from agent.prompt import SYSTEM_PROMPT
from dotenv import load_dotenv
import os
load_dotenv()

class Agent:
    def __init__(self, db_path='chats.db'):
        """Initialize the Agent with a State object and OpenAI client."""
        self.state = State(db_path=db_path)
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
        
        # Call the OpenAI Responses API
        
        response = self.client.responses.create(
            model="gpt-5-nano",
            prompt={
                "id": "pmpt_68e4d02f6ab08195a6621108115f8aca015cb2eaf85af6ca"
            },
            tools=[{ "type": "web_search_preview" }],
            input=context
        )

        # Extract all output items from the response (assistant messages and tool calls)
        for output_item in response.output:
            if hasattr(output_item, 'type'):
                # Handle message type
                if output_item.type == 'message':
                    message_obj = {
                        "type": "message",
                        "role": output_item.role,
                        "content": output_item.content[0].text if output_item.content else ""
                    }
                    self.state.add_context(user_id, message_obj)
                    assistant_message = message_obj
        
        return assistant_message

