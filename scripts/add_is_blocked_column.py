
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    if env == 'PROD' and database_url:
        import psycopg2
        conn = psycopg2.connect(database_url)
        return conn, 'postgres'
    else:
        # From scripts/ -> go up 2 levels -> chats.db (in Donna/ folder)
        # __file__ = .../zarie/scripts/add_is_blocked_column.py
        # dirname = .../zarie/scripts
        # dirname = .../zarie
        # dirname = .../Donna
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'chats.db')
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'

def add_is_blocked_column():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    print(f"Connected to database ({db_type})...")
    
    try:
        if db_type == 'postgres':
            print("Adding is_blocked column to PostgreSQL users table...")
            cursor.execute("""
                ALTER TABLE users 
                ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE;
            """)
        else:
            print("Checking/Adding is_blocked column to SQLite users table...")
            # Check if column exists
            cursor.execute("PRAGMA table_info(users)")
            columns = [info[1] for info in cursor.fetchall()]
            
            if 'is_blocked' not in columns:
                cursor.execute("""
                    ALTER TABLE users 
                    ADD COLUMN is_blocked BOOLEAN DEFAULT 0;
                """)
                print("Column 'is_blocked' added successfully.")
            else:
                print("Column 'is_blocked' already exists.")
        
        conn.commit()
        print("Migration successful!")
        
    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    add_is_blocked_column()
