#!/usr/bin/env python3
"""
Script to delete all records from chats_context, worker_agent_context, time_events, 
and worker_agent_directory_v2 for all users EXCEPT specified user IDs.

This is useful for cleaning up production data while preserving specific users.

Usage:
    python scripts/cleanup_worker_data.py --keep-users "7580670088,868383156" [--confirm]

Example:
    python scripts/cleanup_worker_data.py --keep-users "7580670088,868383156" --confirm
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

def cleanup_worker_data_sqlite(keep_user_ids, db_path):
    """Delete worker data for all users except specified ones from SQLite database."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    try:
        print(f"Cleaning up worker data for all users EXCEPT: {', '.join(keep_user_ids)}")
        print(f"Database: SQLite ({db_path})")
        
        # Create placeholders for SQL IN clause
        placeholders = ','.join('?' * len(keep_user_ids))
        
        # First, get counts of what will be deleted
        print("\nCounting records to be deleted...")
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM chats_context 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        chats_context_count = cursor.fetchone()[0]
        print(f"  - chats_context: {chats_context_count} records")
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM worker_agent_context 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        context_count = cursor.fetchone()[0]
        print(f"  - worker_agent_context: {context_count} records")
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM time_events 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        time_events_count = cursor.fetchone()[0]
        print(f"  - time_events: {time_events_count} records")
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM worker_agent_directory_v2 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        directory_count = cursor.fetchone()[0]
        print(f"  - worker_agent_directory_v2: {directory_count} records")
        
        total_count = chats_context_count + context_count + time_events_count + directory_count
        print(f"\nTotal records to be deleted: {total_count}")
        
        if total_count == 0:
            print("\nNo records to delete. Exiting.")
            return
        
        # Delete from chats_context
        print("\nDeleting from chats_context...")
        cursor.execute(f"""
            DELETE FROM chats_context 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        rows_deleted = cursor.rowcount
        print(f"  ✓ Deleted {rows_deleted} rows from chats_context")
        
        # Delete from worker_agent_context
        print("Deleting from worker_agent_context...")
        cursor.execute(f"""
            DELETE FROM worker_agent_context 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        rows_deleted = cursor.rowcount
        print(f"  ✓ Deleted {rows_deleted} rows from worker_agent_context")
        
        # Delete from time_events
        print("Deleting from time_events...")
        cursor.execute(f"""
            DELETE FROM time_events 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        rows_deleted = cursor.rowcount
        print(f"  ✓ Deleted {rows_deleted} rows from time_events")
        
        # Delete from worker_agent_directory_v2
        print("Deleting from worker_agent_directory_v2...")
        cursor.execute(f"""
            DELETE FROM worker_agent_directory_v2 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        rows_deleted = cursor.rowcount
        print(f"  ✓ Deleted {rows_deleted} rows from worker_agent_directory_v2")
        
        # Commit all changes
        conn.commit()
        print(f"\n✓ Successfully cleaned up worker data")
        print(f"✓ Preserved data for users: {', '.join(keep_user_ids)}")
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error cleaning up worker data: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

def cleanup_worker_data_postgres(keep_user_ids):
    """Delete worker data for all users except specified ones from PostgreSQL database."""
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        print(f"Cleaning up worker data for all users EXCEPT: {', '.join(keep_user_ids)}")
        print(f"Database: PostgreSQL (Railway)")
        
        # Create placeholders for SQL IN clause
        placeholders = ','.join(['%s'] * len(keep_user_ids))
        
        # First, get counts of what will be deleted
        print("\nCounting records to be deleted...")
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM chats_context 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        chats_context_count = cursor.fetchone()[0]
        print(f"  - chats_context: {chats_context_count} records")
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM worker_agent_context 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        context_count = cursor.fetchone()[0]
        print(f"  - worker_agent_context: {context_count} records")
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM time_events 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        time_events_count = cursor.fetchone()[0]
        print(f"  - time_events: {time_events_count} records")
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM worker_agent_directory_v2 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        directory_count = cursor.fetchone()[0]
        print(f"  - worker_agent_directory_v2: {directory_count} records")
        
        total_count = chats_context_count + context_count + time_events_count + directory_count
        print(f"\nTotal records to be deleted: {total_count}")
        
        if total_count == 0:
            print("\nNo records to delete. Exiting.")
            return
        
        # Delete from chats_context
        print("\nDeleting from chats_context...")
        cursor.execute(f"""
            DELETE FROM chats_context 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        rows_deleted = cursor.rowcount
        print(f"  ✓ Deleted {rows_deleted} rows from chats_context")
        
        # Delete from worker_agent_context
        print("Deleting from worker_agent_context...")
        cursor.execute(f"""
            DELETE FROM worker_agent_context 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        rows_deleted = cursor.rowcount
        print(f"  ✓ Deleted {rows_deleted} rows from worker_agent_context")
        
        # Delete from time_events
        print("Deleting from time_events...")
        cursor.execute(f"""
            DELETE FROM time_events 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        rows_deleted = cursor.rowcount
        print(f"  ✓ Deleted {rows_deleted} rows from time_events")
        
        # Delete from worker_agent_directory_v2
        print("Deleting from worker_agent_directory_v2...")
        cursor.execute(f"""
            DELETE FROM worker_agent_directory_v2 
            WHERE user_id NOT IN ({placeholders})
        """, keep_user_ids)
        rows_deleted = cursor.rowcount
        print(f"  ✓ Deleted {rows_deleted} rows from worker_agent_directory_v2")
        
        # Commit all changes
        conn.commit()
        print(f"\n✓ Successfully cleaned up worker data")
        print(f"✓ Preserved data for users: {', '.join(keep_user_ids)}")
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error cleaning up worker data: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()

def main():
    parser = argparse.ArgumentParser(
        description="Delete worker data for all users except specified ones"
    )
    parser.add_argument(
        "--keep-users",
        type=str,
        required=True,
        help="Comma-separated list of user IDs to keep (e.g., '7580670088,868383156')"
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
    
    # Parse keep_users
    keep_user_ids = [uid.strip() for uid in args.keep_users.split(',')]
    
    if not keep_user_ids:
        print("✗ Error: No user IDs provided to keep", file=sys.stderr)
        sys.exit(1)
    
    # Determine database type
    db_type = determine_db_type(args.db_path or "chats.db")
    
    # If not confirming, ask for confirmation
    if not args.confirm:
        print(f"⚠️  WARNING: This will delete ALL data for users EXCEPT:")
        for uid in keep_user_ids:
            print(f"    • {uid}")
        print()
        print("This will DELETE from the following tables:")
        print("  • chats_context")
        print("  • worker_agent_context")
        print("  • time_events")
        print("  • worker_agent_directory_v2")
        print()
        print(f"Database type: {db_type.upper()}")
        if db_type == 'postgres':
            print("⚠️  This will run on PRODUCTION (Railway) database!")
        print()
        response = input("Are you sure you want to continue? Type 'DELETE' to confirm: ")
        if response != 'DELETE':
            print("Aborted.")
            sys.exit(0)
    
    # Execute deletion
    if db_type == 'postgres':
        cleanup_worker_data_postgres(keep_user_ids)
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
        
        cleanup_worker_data_sqlite(keep_user_ids, str(db_path))

if __name__ == "__main__":
    main()
