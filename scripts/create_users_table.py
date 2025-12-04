"""
Migration script to create users table
Supports both SQLite (local) and PostgreSQL (Railway)
"""
import os

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_db_connection():
    """Get database connection - respects ENV variable for safety"""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    # Only use postgres if ENV=PROD and DATABASE_URL is set
    if env == 'PROD' and database_url:
        import psycopg2
        conn = psycopg2.connect(database_url)
        return conn, 'postgres'
    else:
        import sqlite3
        # Path: scripts/ -> alpha-v0.1/ -> .. -> Donna/ -> chats.db
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'chats.db')
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'

def create_users_table():
    """Create users table"""
    
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    print(f"Connected to {db_type.upper()} database")
    
    try:
        # Create users table
        print("Creating users table...")
        if db_type == 'postgres':
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id TEXT NOT NULL UNIQUE,
                    name TEXT,
                    telegram_username TEXT
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id TEXT NOT NULL UNIQUE,
                    name TEXT,
                    telegram_username TEXT
                )
            """)
        
        # Create index on telegram_id for faster lookups
        print("Creating index on telegram_id...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_telegram_id 
            ON users(telegram_id)
        """)
        
        conn.commit()
        print("\n✅ Users table created successfully!")
        
        # Display table info
        if db_type == 'postgres':
            print("\n--- users table schema ---")
            cursor.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_name = 'users'
                ORDER BY ordinal_position
            """)
            for row in cursor.fetchall():
                nullable = "NULL" if row[2] == 'YES' else "NOT NULL"
                print(f"  {row[0]}: {row[1]} {nullable}")
        else:
            print("\n--- users table schema ---")
            cursor.execute("PRAGMA table_info(users)")
            for row in cursor.fetchall():
                nullable = "NULL" if not row[3] else "NOT NULL"
                print(f"  {row[1]}: {row[2]} {nullable}")
        
    except Exception as e:
        print(f"❌ Error creating table: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    print("Migration Script: Creating Users Table")
    print("Supports both SQLite (local) and PostgreSQL (Railway)")
    print()
    create_users_table()

