import os
import sqlite3
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_db_connection():
    """Get database connection based on environment."""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    use_postgres = (env == 'PROD' and database_url is not None)
    
    if use_postgres:
        import psycopg2
        print("Connecting to PostgreSQL database...")
        return psycopg2.connect(database_url), 'postgres'
    else:
        # Hardcoded path based on user instruction: Documents/Donna/chats.db
        # Assuming script is run from /Users/sankalpphadnis/Documents/Donna/zarie
        # So we go up one level to Donna/ and then to chats.db
        
        # /Users/sankalpphadnis/Documents/Donna/zarie/scripts/add_summary_columns.py
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Go up 2 levels: scripts/ -> zarie/ -> Donna/
        base_dir = os.path.dirname(os.path.dirname(current_dir))
        db_path = os.path.join(base_dir, 'chats.db')
        
        print(f"Connecting to SQLite database at {db_path}...")
        return sqlite3.connect(db_path), 'sqlite'

def add_columns():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Add running_summary to users
        print("Adding running_summary to users table...")
        if db_type == 'postgres':
            cursor.execute("""
                ALTER TABLE users 
                ADD COLUMN IF NOT EXISTS running_summary TEXT;
            """)
        else:
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN running_summary TEXT")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    print("Column running_summary already exists in users.")
                else:
                    raise e

        # 2. Add is_summarised to chats_context
        print("Adding is_summarised to chats_context table...")
        if db_type == 'postgres':
            cursor.execute("""
                ALTER TABLE chats_context 
                ADD COLUMN IF NOT EXISTS is_summarised BOOLEAN DEFAULT FALSE;
            """)
            cursor.execute("UPDATE chats_context SET is_summarised = FALSE WHERE is_summarised IS NULL")
        else:
            try:
                cursor.execute("ALTER TABLE chats_context ADD COLUMN is_summarised BOOLEAN DEFAULT 0")
                cursor.execute("UPDATE chats_context SET is_summarised = 0 WHERE is_summarised IS NULL")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    print("Column is_summarised already exists in chats_context.")
                else:
                    raise e
        
        conn.commit()
        print("Migration completed successfully.")
        
    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    add_columns()
