#!/usr/bin/env python3
"""
Migration: Create slack_users cache table
Run: python scripts/03_create_slack_users_cache.py
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS slack_users (
                    slack_user_id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    display_name TEXT,
                    real_name TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_slack_users_team 
                ON slack_users(team_id)
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS slack_users (
                    slack_user_id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    display_name TEXT,
                    real_name TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_slack_users_team 
                ON slack_users(team_id)
            """)
        
        conn.commit()
        print("✓ Created slack_users table")
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
