"""
Migration script to convert context from old format (with 'type' wrappers)
to new LiteLLM format (direct message format).

Safe to run multiple times - idempotent.
"""

import sqlite3
import json
import os
from dotenv import load_dotenv

load_dotenv()

def convert_context_item(item):
    """Convert a single context item from old format to LiteLLM format."""
    item_type = item.get("type")
    
    if item_type == "message":
        # Simple message: keep role and content
        return {
            "role": item["role"],
            "content": item["content"]
        }
    
    elif item_type == "tool_call_request":
        # Tool call request: convert to assistant message with tool_calls
        tool_calls = []
        for tc in item.get("tool_calls", []):
            tool_call = {
                "id": tc["id"],
                "type": tc.get("type", "function"),  # Add 'type' if missing
                "function": tc["function"]
            }
            tool_calls.append(tool_call)
        
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls
        }
    
    elif item_type == "tool_call_response":
        # Tool response: keep as tool message
        content = item["content"]
        # Ensure content is string (JSON if dict/list)
        if isinstance(content, (dict, list)):
            content = json.dumps(content)
        
        return {
            "role": "tool",
            "tool_call_id": item["tool_call_id"],
            "name": item["name"],
            "content": content
        }
    
    else:
        # Already in new format or unknown - return as is
        return item


def migrate_sqlite(db_path):
    """Migrate SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all users and their contexts
    cursor.execute("SELECT user_id, context FROM chats")
    rows = cursor.fetchall()
    
    migrated_count = 0
    
    for user_id, context_blob in rows:
        context = json.loads(context_blob)
        
        # Check if migration is needed (look for 'type' field in first item)
        if context and context[0].get("type") in ["message", "tool_call_request", "tool_call_response"]:
            # Convert all items
            new_context = [convert_context_item(item) for item in context]
            
            # Update database
            cursor.execute(
                "UPDATE chats SET context = ? WHERE user_id = ?",
                (json.dumps(new_context), user_id)
            )
            migrated_count += 1
            print(f"✓ Migrated user: {user_id}")
    
    conn.commit()
    conn.close()
    
    return migrated_count


def migrate_postgres():
    """Migrate PostgreSQL database."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_PUBLIC_URL')
    
    # Only proceed if ENV=PROD and DATABASE_URL is set
    if env != 'PROD' or not database_url:
        print("❌ ENV must be 'PROD' and DATABASE_PUBLIC_URL must be set")
        return 0
    
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get all users and their contexts
    cursor.execute("SELECT user_id, context FROM chats")
    rows = cursor.fetchall()
    
    migrated_count = 0
    
    for row in rows:
        user_id = row['user_id']
        context_blob = row['context']
        context = json.loads(context_blob)
        
        # Check if migration is needed
        if context and context[0].get("type") in ["message", "tool_call_request", "tool_call_response"]:
            # Convert all items
            new_context = [convert_context_item(item) for item in context]
            
            # Update database
            cursor.execute(
                "UPDATE chats SET context = %s WHERE user_id = %s",
                (json.dumps(new_context), user_id)
            )
            migrated_count += 1
            print(f"✓ Migrated user: {user_id}")
    
    conn.commit()
    conn.close()
    
    return migrated_count


def main():
    """Run the migration."""
    print("Starting context format migration...")
    print("=" * 50)
    
    database_url = os.getenv('DATABASE_URL')
    
    if database_url:
        print("Detected PostgreSQL (Railway)")
        try:
            migrated = migrate_postgres()
            print("=" * 50)
            print(f"✅ Migration complete! Migrated {migrated} users.")
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            raise
    else:
        print("Detected SQLite (local)")
        db_path = 'chats.db'
        try:
            migrated = migrate_sqlite(db_path)
            print("=" * 50)
            print(f"✅ Migration complete! Migrated {migrated} users.")
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            raise


if __name__ == "__main__":
    main()
