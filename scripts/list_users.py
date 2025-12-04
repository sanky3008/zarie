#!/usr/bin/env python3
"""
Script to list all user IDs in the chats_context table.
"""

import os
import sqlite3
from dotenv import load_dotenv

# Load environment variables
try:
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        load_dotenv()
except Exception as e:
    print(f"Warning: Could not load .env file: {e}")

def main():
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    if env == 'PROD' and database_url:
        print(f"Using PostgreSQL database...")
        try:
            import psycopg2
            conn = psycopg2.connect(database_url)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT user_id, COUNT(*) as msg_count
                FROM chats_context
                GROUP BY user_id
                ORDER BY msg_count DESC
            """)
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            print(f"Error connecting to PostgreSQL: {e}")
            return
    else:
        print(f"Using SQLite database...")
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
            'chats.db'
        )
        if not os.path.exists(db_path):
            print(f"Database not found at {db_path}")
            return
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT user_id, COUNT(*) as msg_count
            FROM chats_context
            GROUP BY user_id
            ORDER BY msg_count DESC
        """)
        rows = cursor.fetchall()
        conn.close()
    
    if not rows:
        print("No users found in database")
        return
    
    print(f"\n{'='*60}")
    print(f"Users in chats_context:")
    print(f"{'='*60}\n")
    print(f"{'User ID':<30} {'Message Count':<15}")
    print(f"{'-'*60}")
    
    total_msgs = 0
    for user_id, count in rows:
        print(f"{user_id:<30} {count:<15}")
        total_msgs += count
    
    print(f"{'-'*60}")
    print(f"{'TOTAL':<30} {total_msgs:<15}\n")
    print(f"Usage: python analyze_tokens.py <user_id>\n")

if __name__ == "__main__":
    main()

