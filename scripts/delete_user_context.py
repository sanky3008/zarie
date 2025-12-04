#!/usr/bin/env python3
"""
Script to delete chat context for a particular user ID for context optimization.
This removes only the chat history and context from chats_context table.
Worker agents and time events remain untouched.

Usage:
    python scripts/delete_user_context.py <user_id>

Example:
    python scripts/delete_user_context.py "12345"
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_db_connection(db_path):
    """Get SQLite database connection."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def get_postgres_connection():
    """Get PostgreSQL database connection."""
    import psycopg2
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable not set")
    return psycopg2.connect(database_url)

def determine_db_type(db_path):
    """Determine which database to use based on environment."""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    # Use PostgreSQL if ENV=PROD and DATABASE_URL is set
    if env == 'PROD' and database_url is not None:
        return 'postgres'
    else:
        return 'sqlite'

def delete_user_context_sqlite(user_id, db_path):
    """Delete chat context for a user from SQLite database (chats_context table only)."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    try:
        print(f"Deleting chat context for user_id: {user_id}")
        
        # Delete from chats_context table only
        print("  - Deleting from chats_context...")
        cursor.execute("DELETE FROM chats_context WHERE user_id = ?", (user_id,))
        rows_deleted = cursor.rowcount
        print(f"    Deleted {rows_deleted} rows from chats_context")
        
        # Commit all changes
        conn.commit()
        print(f"\n✓ Successfully deleted chat context for user_id: {user_id}")
        print("Note: Worker agents and time events have been preserved.")
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error deleting user context: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

def delete_user_context_postgres(user_id):
    """Delete chat context for a user from PostgreSQL database (chats_context table only)."""
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        print(f"Deleting chat context for user_id: {user_id}")
        
        # Delete from chats_context table only
        print("  - Deleting from chats_context...")
        cursor.execute("DELETE FROM chats_context WHERE user_id = %s", (user_id,))
        rows_deleted = cursor.rowcount
        print(f"    Deleted {rows_deleted} rows from chats_context")
        
        # Commit all changes
        conn.commit()
        print(f"\n✓ Successfully deleted chat context for user_id: {user_id}")
        print("Note: Worker agents and time events have been preserved.")
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error deleting user context: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()

def main():
    parser = argparse.ArgumentParser(
        description="Delete chat context for a particular user ID (context optimization)"
    )
    parser.add_argument(
        "user_id",
        type=str,
        help="The user ID to delete chat context for"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to the SQLite database (only used for LOCAL/SQLite mode)"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt (useful for automation)"
    )
    
    args = parser.parse_args()
    user_id = args.user_id
    
    # Determine database type
    db_type = determine_db_type(args.db_path or "chats.db")
    
    # If not confirming, ask for confirmation
    if not args.confirm:
        print(f"⚠️  WARNING: This will delete all chat context for user_id: {user_id}")
        print("This will remove:")
        print("  • All chat messages and conversation history")
        print()
        print("This will NOT remove:")
        print("  • Worker agents and their configurations")
        print("  • Time events and reminders")
        print()
        response = input("Are you sure you want to continue? Type 'yes' to confirm: ")
        if response.lower() != 'yes':
            print("Aborted.")
            sys.exit(0)
    
    # Execute deletion
    if db_type == 'postgres':
        delete_user_context_postgres(user_id)
    else:
        # Determine database path
        if args.db_path:
            db_path = args.db_path
        else:
            # Default path relative to script location
            script_dir = Path(__file__).parent.parent
            db_path = script_dir / "chats.db"
        
        if not os.path.exists(db_path):
            print(f"✗ Database file not found: {db_path}", file=sys.stderr)
            sys.exit(1)
        
        delete_user_context_sqlite(user_id, str(db_path))

if __name__ == "__main__":
    main()

