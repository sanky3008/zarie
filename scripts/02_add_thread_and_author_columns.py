#!/usr/bin/env python3
"""
Migration: Add thread_ts, slack_ts, author_id, author_name columns to chats_context
Run: python scripts/02_add_thread_and_author_columns.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from user_manager import get_db_connection

def migrate():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    print(f"Running migration on {db_type}...")
    
    columns_to_add = ['thread_ts', 'slack_ts', 'author_id', 'author_name']
    
    try:
        if db_type == 'postgres':
            for col in columns_to_add:
                cursor.execute(f"ALTER TABLE chats_context ADD COLUMN IF NOT EXISTS {col} TEXT")
                print(f"  Added/verified {col} column")
            
            # Create index
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chats_context_thread 
                ON chats_context(user_id, thread_ts)
            """)
            print("  Created/verified thread index")
            
        else:
            # SQLite
            cursor.execute("PRAGMA table_info(chats_context)")
            existing_columns = [info[1] for info in cursor.fetchall()]
            
            for col in columns_to_add:
                if col not in existing_columns:
                    cursor.execute(f"ALTER TABLE chats_context ADD COLUMN {col} TEXT")
                    print(f"  Added {col} column")
                else:
                    print(f"  {col} column already exists")
            
            # Create index
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chats_context_thread 
                ON chats_context(user_id, thread_ts)
            """)
            print("  Created/verified thread index")
        
        conn.commit()
        print("✓ Migration complete")
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
