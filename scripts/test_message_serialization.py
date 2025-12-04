#!/usr/bin/env python3
"""
Test to understand the message serialization issue.
Shows what happens when we try to serialize LiteLLM message objects.
"""

import json
import sys

# Mock a LiteLLM response message object
class MockToolCall:
    def __init__(self, id, name, args):
        self.id = id
        self.function = type('obj', (object,), {'name': name, 'arguments': args})()

class MockMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

def estimate_tokens(text):
    """Rough token estimation: 1 token ≈ 4 characters"""
    if not text:
        return 0
    return len(text) / 4

def main():
    print(f"\n{'='*80}")
    print("Testing Message Serialization Issues")
    print(f"{'='*80}\n")
    
    # Scenario 1: Proper message dict
    print("Scenario 1: Proper message dict (CORRECT):")
    proper_msg = {
        "role": "assistant",
        "content": "I'll help you with that",
        "tool_calls": []
    }
    try:
        serialized = json.dumps(proper_msg)
        tokens = estimate_tokens(serialized)
        print(f"  ✓ Serialized successfully")
        print(f"  Tokens: {int(tokens):,}")
        print(f"  Size: {len(serialized):,} chars\n")
    except Exception as e:
        print(f"  ✗ Error: {e}\n")
    
    # Scenario 2: LiteLLM message object
    print("Scenario 2: LiteLLM message object (PROBLEMATIC):")
    mock_msg = MockMessage(
        content="I'll help you with that",
        tool_calls=[]
    )
    try:
        # This will fail because the object isn't JSON serializable
        serialized = json.dumps(mock_msg)
        print(f"  ✓ Serialized successfully")
    except TypeError as e:
        print(f"  ✗ JSON serialization fails: {type(e).__name__}")
        print(f"     Trying to convert to string instead...")
        
        # What happens if we convert to string?
        str_version = str(mock_msg)
        print(f"     str(mock_msg) = {str_version}")
        
        # This would be a HUGE problem if LiteLLM passes this to JSON
        tokens = estimate_tokens(str_version)
        print(f"     Tokens if converted to string: {int(tokens):,}\n")
    
    # Scenario 3: Message with tool calls  
    print("Scenario 3: Message with tool calls (tool_call object):")
    tool_call = MockToolCall(
        id="call_123",
        name="invoke_worker_agent",
        args='{"agent_name":"reminder","user_id":"123","purpose":"reminders","message":"test"}'
    )
    
    # Trying to append this to messages list
    messages = []
    messages.append(mock_msg)
    
    print(f"  Messages list: {messages}")
    print(f"  Type of first message: {type(messages[0])}")
    
    # When this gets passed to litellm.acompletion, what happens?
    print(f"\n  If we try to JSON dump the messages list:")
    try:
        json.dumps(messages)
    except TypeError as e:
        print(f"  ✗ Error: {e}")
        print(f"     This is the problem! The messages contain non-serializable objects.")
    
    print(f"\n{'='*80}")
    print("CONCLUSION:")
    print(f"{'='*80}")
    print("""
The issue is at line 254 in agent.py:
    messages.append(assistant_msg)

assistant_msg is a LiteLLM message object, NOT a dict. When this gets
passed back to litellm.acompletion() for the next iteration, it tries
to serialize it, causing issues.

THE FIX:
Instead of appending the raw LiteLLM object, extract the fields:

    messages.append({
        "role": "assistant",
        "content": assistant_msg.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }
            }
            for tc in (assistant_msg.tool_calls or [])
        ]
    })
    messages.extend(tool_responses)
""")

if __name__ == "__main__":
    main()

