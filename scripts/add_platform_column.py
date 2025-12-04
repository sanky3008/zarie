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
        # Go up 3 levels from zarie/scripts/add_platform_column.py -> zarie/scripts/ -> zarie/ -> Donna/ -> chats.db
        # Wait, user_manager.py is in zarie/.
        # If user_manager.py uses os.path.dirname(os.path.dirname(__file__)), 'chats.db'
        # user_manager.py is in /Users/sankalpphadnis/Documents/Donna/zarie/user_manager.py
        # dirname is /Users/sankalpphadnis/Documents/Donna/zarie
        # dirname(dirname) is /Users/sankalpphadnis/Documents/Donna
        # So chats.db is in /Users/sankalpphadnis/Documents/Donna/chats.db
        
        # This script is in /Users/sankalpphadnis/Documents/Donna/zarie/scripts/add_platform_column.py
        # dirname is /Users/sankalpphadnis/Documents/Donna/zarie/scripts
        # dirname(dirname) is /Users/sankalpphadnis/Documents/Donna/zarie
        # dirname(dirname(dirname)) is /Users/sankalpphadnis/Documents/Donna
        
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'chats.db')
        print(f"Database path: {db_path}")
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'

def add_column():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        print(f"Adding 'platform' column to users table...")
        
        if db_type == 'postgres':
            # Check if column exists first to avoid error
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='users' AND column_name='platform';
            """)
            if cursor.fetchone():
                print("Column 'platform' already exists.")
            else:
                cursor.execute("ALTER TABLE users ADD COLUMN platform TEXT DEFAULT 'telegram';")
                print("Column 'platform' added successfully.")
        else:
            # SQLite
            # Check if column exists
            cursor.execute("PRAGMA table_info(users);")
            columns = [info[1] for info in cursor.fetchall()]
            if 'platform' in columns:
                print("Column 'platform' already exists.")
            else:
                cursor.execute("ALTER TABLE users ADD COLUMN platform TEXT DEFAULT 'telegram';")
                print("Column 'platform' added successfully.")
        
        conn.commit()
        print("Migration completed successfully.")
        
    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    add_column()
