import os
import sqlite3
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    if env == 'PROD' and database_url:
        conn = psycopg2.connect(database_url)
        return conn, 'postgres'
    else:
        # Script is in zarie/scripts/ -> go up 3 levels to Donna/ -> chats.db
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'chats.db')
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'

def add_team_id_column():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        print(f"Connected to {db_type} database.")
        
        if db_type == 'postgres':
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS team_id TEXT;")
        else:
            # SQLite doesn't support IF NOT EXISTS in ALTER TABLE directly in older versions, 
            # but we can check pragma or just try/except.
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN team_id TEXT;")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    print("Column team_id already exists.")
                else:
                    raise e
        
        conn.commit()
        print("Successfully added team_id column to users table.")
        
    except Exception as e:
        print(f"Error adding column: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    add_team_id_column()
