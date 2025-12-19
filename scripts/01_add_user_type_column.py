#!/usr/bin/env python3
"""
Migration: Add user_type column to users table
Run: python scripts/01_add_user_type_column.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from user_manager import get_db_connection

def migrate():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    print(f"Running migration on {db_type}...")
    
    try:
        if db_type == 'postgres':
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS user_type TEXT DEFAULT 'user'")
        else:
            # SQLite doesn't have IF NOT EXISTS for ALTER TABLE
            cursor.execute("PRAGMA table_info(users)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'user_type' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN user_type TEXT DEFAULT 'user'")
                print("  Added user_type column")
            else:
                print("  user_type column already exists")
        
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
