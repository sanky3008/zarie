#!/usr/bin/env python3
"""
Script to test token counting with DeepSeek via LiteLLM.

This script:
1. Takes a user ID and message as input
2. Retrieves the user's context from the database
3. Appends the message to the context
4. Calls DeepSeek using LiteLLM
5. Calculates and prints token usage for prompt and output

Usage:
    python scripts/test_token_count.py <user_id> <message>
    
Example:
    python scripts/test_token_count.py user123 "Hello, how are you?"

Requirements:
    - DATABASE_URL (optional, uses local SQLite if not set)
    - OPENAI_API_KEY (for token counting via LiteLLM)
    - ENV variable (optional, defaults to LOCAL)
"""

import sys
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from agent.state.state import State
from agent.prompt import get_system_prompt
import litellm

# Load environment variables
load_dotenv()

def validate_environment():
    """Validate that required environment variables are set."""
    env = os.getenv('ENV', 'LOCAL').upper()
    
    # Check for OPENAI_API_KEY which is needed for token counting
    if not os.getenv('OPENAI_API_KEY'):
        print("⚠️  Warning: OPENAI_API_KEY not set. Token counting may not work properly.")
        print("   Please set OPENAI_API_KEY in your environment or .env file")
    
    # If PROD environment, check for DATABASE_URL
    if env == 'PROD':
        if not os.getenv('DATABASE_URL'):
            raise EnvironmentError(
                "❌ PROD environment requires DATABASE_URL to be set. "
                "Please set DATABASE_URL in your environment or .env file"
            )
        print(f"✓ Using PROD environment with DATABASE_URL")
    else:
        print(f"✓ Using LOCAL environment (SQLite)")


def prepare_messages(user_id, state):
    """
    Prepare messages array for LLM from context.
    Similar to Agent._prepare_messages() including system prompt.
    """
    context_blob = state.get_context(user_id)
    messages = json.loads(context_blob) if context_blob else []
    
    # Add system prompt (same as in Agent._prepare_messages())
    system_prompt = get_system_prompt(user_id)
    if system_prompt:
        messages.insert(0, {
            "role": "system",
            "content": system_prompt
        })
    
    return messages


def create_user_message(message):
    """Create a formatted user message with date and time."""
    # Convert to IST (Indian Standard Time)
    ist_timezone = ZoneInfo("Asia/Kolkata")
    timestamp = datetime.now(ist_timezone)
    
    # Get day and date components
    day_name = timestamp.strftime("%A")
    day = timestamp.day
    month = timestamp.strftime("%b")
    year = timestamp.year
    
    # Get proper ordinal suffix
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    
    date_str = f"{day_name}, {day}{suffix} {month} {year}"
    time_str = timestamp.strftime("%H:%M")
    
    return {
        "role": "user",
        "content": f"Date: {date_str}\nTime: {time_str}\nFROM: test_script\nMessage: {message}"
    }


def calculate_tokens_by_role(model, messages):
    """
    Calculate token counts by role type.
    
    Args:
        model: Model name (e.g., "deepseek/deepseek-chat")
        messages: List of message dictionaries
    
    Returns:
        Dictionary with token counts bifurcated by role
    """
    token_by_role = {}
    
    try:
        for message in messages:
            role = message.get('role', 'unknown')
            
            # Count tokens for this single message
            tokens = litellm.token_counter(
                model=model,
                messages=[message]
            )
            
            if role not in token_by_role:
                token_by_role[role] = 0
            token_by_role[role] += tokens
        
        # Calculate total
        total = sum(token_by_role.values())
        
        return {
            "by_role": token_by_role,
            "total": total
        }
    except Exception as e:
        print(f"⚠️  Error calculating tokens by role: {e}")
        return {
            "by_role": {},
            "total": 0,
            "error": str(e)
        }


def calculate_tokens(model, messages, response_content=None):
    """
    Calculate token counts using LiteLLM's token_counter.
    
    Args:
        model: Model name (e.g., "deepseek/deepseek-chat")
        messages: List of message dictionaries
        response_content: Optional response content to count completion tokens
    
    Returns:
        Dictionary with prompt_tokens, completion_tokens, and total_tokens
    """
    try:
        # Count prompt tokens
        prompt_tokens = litellm.token_counter(
            model=model,
            messages=messages
        )
        
        # Count completion tokens if response provided
        completion_tokens = 0
        if response_content:
            completion_tokens = litellm.token_counter(
                model=model,
                text=response_content
            )
        
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
    except Exception as e:
        print(f"⚠️  Error calculating tokens: {e}")
        # Return zeros if calculation fails
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error": str(e)
        }


async def main(user_id, user_message):
    """Main function to process the user message and interact with DeepSeek."""
    print(f"\n{'='*60}")
    print(f"Token Counting Test - DeepSeek via LiteLLM")
    print(f"{'='*60}\n")
    
    # Validate environment
    print("Validating environment...")
    validate_environment()
    print()
    
    try:
        # Initialize State
        print(f"Initializing database connection...")
        state = State()
        print(f"✓ Database connection established\n")
        
        # Get user context
        print(f"Retrieving context for user: {user_id}")
        messages = prepare_messages(user_id, state)
        print(f"✓ Retrieved {len(messages)} messages from context\n")
        
        # Create and append user message
        formatted_message = create_user_message(user_message)
        messages.append(formatted_message)
        print(f"User Message:\n{formatted_message['content']}\n")
        
        # Calculate prompt tokens BEFORE calling API (with role bifurcation)
        print(f"Calculating prompt tokens by role...")
        role_breakdown = calculate_tokens_by_role(
            "deepseek/deepseek-chat",
            messages
        )
        prompt_token_count = role_breakdown['total']
        print(f"✓ Prompt tokens (total): {prompt_token_count}")
        print(f"  Breakdown by role:")
        for role, count in sorted(role_breakdown['by_role'].items()):
            print(f"    - {role}: {count}")
        print()
        
        # Call DeepSeek
        print(f"Calling DeepSeek API...")
        response = await litellm.acompletion(
            model="deepseek/deepseek-chat",
            messages=messages,
            timeout=30,
            num_retries=2
        )
        
        assistant_message = response.choices[0].message.content
        print(f"✓ Received response from DeepSeek\n")
        
        # Get token usage from response (if available)
        completion_tokens = 0
        if hasattr(response, 'usage') and response.usage:
            if hasattr(response.usage, 'completion_tokens'):
                completion_tokens = response.usage.completion_tokens
                print(f"Tokens from API response:")
                print(f"  - Completion tokens: {completion_tokens}")
        
        # If API didn't provide completion tokens, calculate manually
        if completion_tokens == 0:
            print(f"Calculating completion tokens...")
            completion_tokens = litellm.token_counter(
                model="deepseek/deepseek-chat",
                text=assistant_message
            )
        
        # Print results
        print(f"\n{'='*60}")
        print(f"TOKEN USAGE SUMMARY")
        print(f"{'='*60}")
        print(f"\nPrompt Tokens (by role): {prompt_token_count:,}")
        for role, count in sorted(role_breakdown['by_role'].items()):
            percentage = (count / prompt_token_count * 100) if prompt_token_count > 0 else 0
            print(f"  - {role:12} {count:6,} ({percentage:5.1f}%)")
        
        print(f"\nCompletion tokens:  {completion_tokens:,}")
        print(f"Total tokens:       {prompt_token_count + completion_tokens:,}")
        print(f"{'='*60}\n")
        
        # Print assistant response
        print(f"Assistant Response:")
        print(f"{'-'*60}")
        print(f"{assistant_message}")
        print(f"{'-'*60}\n")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def sync_wrapper(user_id, user_message):
    """Wrapper to run async main in sync context."""
    import asyncio
    asyncio.run(main(user_id, user_message))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <user_id> <message>")
        print(f"\nExample:")
        print(f"  python {sys.argv[0]} user123 'What is the capital of France?'")
        sys.exit(1)
    
    user_id = sys.argv[1]
    user_message = " ".join(sys.argv[2:])
    
    sync_wrapper(user_id, user_message)

