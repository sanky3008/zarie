import os
import sqlite3
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_db_connection():
    """Get database connection based on ENV."""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    if env == 'PROD' and database_url:
        print("Connecting to Production Database (Postgres)...")
        import psycopg2
        conn = psycopg2.connect(database_url)
        return conn, 'postgres'
    else:
        print("Connecting to Local Database (SQLite)...")
        # Go up 3 levels from zarie/scripts/add_timezone_column.py -> zarie/scripts/ -> zarie/ -> Donna/ -> chats.db
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'chats.db')
        print(f"Database path: {db_path}")
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'

def add_column():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        print(f"Adding 'timezone' column to users table...")
        
        if db_type == 'postgres':
            # Check if column exists first to avoid error
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='users' AND column_name='timezone';
            """)
            if cursor.fetchone():
                print("Column 'timezone' already exists.")
            else:
                cursor.execute("ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'Asia/Kolkata';")
                print("Column 'timezone' added successfully.")
        else:
            # SQLite
            # Check if column exists
            cursor.execute("PRAGMA table_info(users);")
            columns = [info[1] for info in cursor.fetchall()]
            if 'timezone' in columns:
                print("Column 'timezone' already exists.")
            else:
                cursor.execute("ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'Asia/Kolkata';")
                print("Column 'timezone' added successfully.")
        
        conn.commit()
        print("Migration completed successfully.")
        
    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    add_column()
