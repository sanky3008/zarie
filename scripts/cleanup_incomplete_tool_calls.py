"""
Cleanup script to remove incomplete tool calls from the database.

This script identifies and removes assistant messages with tool_calls that are not
followed by corresponding tool response messages, which cause API errors.

Safe to run multiple times - idempotent.
"""

import sqlite3
import json
import os
from dotenv import load_dotenv

load_dotenv()

def has_incomplete_tool_calls(messages):
    """Check if messages contain incomplete tool calls."""
    for i, msg in enumerate(messages):
        # Check if this is an assistant message with tool calls
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            # Check if next message(s) are tool responses
            has_tool_response = False
            if i + 1 < len(messages):
                next_msg = messages[i + 1]
                if next_msg.get("role") == "tool":
                    has_tool_response = True
            
            # If no tool response found, this is incomplete
            if not has_tool_response:
                return True, i
    
    return False, -1

def clean_messages(messages):
    """Remove incomplete tool calls from messages."""
    cleaned = []
    i = 0
    
    while i < len(messages):
        msg = messages[i]
        
        # Check if this is an assistant message with tool calls
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            # Check if next message(s) are tool responses
            has_tool_response = False
            tool_response_count = 0
            
            # Count consecutive tool responses
            j = i + 1
            while j < len(messages) and messages[j].get("role") == "tool":
                tool_response_count += 1
                j += 1
            
            # If we have tool responses, include the assistant message and all tool responses
            if tool_response_count > 0:
                cleaned.append(msg)  # Add assistant message with tool calls
                # Add all tool responses
                for k in range(i + 1, i + 1 + tool_response_count):
                    cleaned.append(messages[k])
                i = j  # Skip to after tool responses
            else:
                # No tool responses found - skip this incomplete tool call
                tool_call_id = msg.get("tool_calls", [{}])[0].get("id", "unknown")
                print(f"⚠️ Removing incomplete tool call: {tool_call_id}")
                i += 1
        else:
            # Regular message - include it
            cleaned.append(msg)
            i += 1
    
    return cleaned

def cleanup_sqlite(db_path):
    """Cleanup SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all users and their contexts
    cursor.execute("SELECT user_id, context FROM chats")
    rows = cursor.fetchall()
    
    cleaned_count = 0
    
    for user_id, context_blob in rows:
        messages = json.loads(context_blob)
        
        # Check if cleanup is needed
        has_incomplete, _ = has_incomplete_tool_calls(messages)
        
        if has_incomplete:
            print(f"🧹 Cleaning up user: {user_id}")
            cleaned_messages = clean_messages(messages)
            
            # Update database
            cursor.execute(
                "UPDATE chats SET context = ? WHERE user_id = ?",
                (json.dumps(cleaned_messages), user_id)
            )
            cleaned_count += 1
            print(f"✓ Cleaned user: {user_id}")
    
    conn.commit()
    conn.close()
    
    return cleaned_count

def cleanup_postgres():
    """Cleanup PostgreSQL database."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    database_url = os.getenv('DATABASE_PUBLIC_URL')
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get all users and their contexts
    cursor.execute("SELECT user_id, context FROM chats")
    rows = cursor.fetchall()
    
    cleaned_count = 0
    
    for row in rows:
        user_id = row['user_id']
        context_blob = row['context']
        messages = json.loads(context_blob)
        
        # Check if cleanup is needed
        has_incomplete, _ = has_incomplete_tool_calls(messages)
        
        if has_incomplete:
            print(f"🧹 Cleaning up user: {user_id}")
            cleaned_messages = clean_messages(messages)
            
            # Update database
            cursor.execute(
                "UPDATE chats SET context = %s WHERE user_id = %s",
                (json.dumps(cleaned_messages), user_id)
            )
            cleaned_count += 1
            print(f"✓ Cleaned user: {user_id}")
    
    conn.commit()
    conn.close()
    
    return cleaned_count

def main():
    """Run the cleanup."""
    print("Starting incomplete tool calls cleanup...")
    print("=" * 50)
    
    database_url = os.getenv('DATABASE_PUBLIC_URL')
    
    if database_url:
        print("Detected PostgreSQL (Railway)")
        try:
            cleaned = cleanup_postgres()
            print("=" * 50)
            print(f"✅ Cleanup complete! Cleaned {cleaned} users.")
        except Exception as e:
            print(f"❌ Cleanup failed: {e}")
            raise
    else:
        print("Detected SQLite (local)")
        db_path = 'chats.db'
        try:
            cleaned = cleanup_sqlite(db_path)
            print("=" * 50)
            print(f"✅ Cleanup complete! Cleaned {cleaned} users.")
        except Exception as e:
            print(f"❌ Cleanup failed: {e}")
            raise

if __name__ == "__main__":
    main()
