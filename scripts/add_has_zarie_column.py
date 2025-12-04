import os
import sys
import sqlite3
from dotenv import load_dotenv

# Add parent directory to path to allow imports if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
load_dotenv()

def get_db_connection():
    """Get database connection - respects ENV variable"""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    print(f"Current Environment: {env}")
    
    # Only use postgres if ENV=PROD and DATABASE_URL is set
    if env == 'PROD' and database_url:
        print("Connecting to Railway PostgreSQL database...")
        try:
            import psycopg2
            conn = psycopg2.connect(database_url)
            return conn, 'postgres'
        except ImportError:
            print("Error: psycopg2 module not found. Please install it to connect to PostgreSQL.")
            sys.exit(1)
        except Exception as e:
            print(f"Error connecting to PostgreSQL: {e}")
            sys.exit(1)
    else:
        # Use SQLite for local development
        # Script is in: zarie/scripts/
        # DB is in: Donna/chats.db (parent of zarie)
        
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # Donna/
        db_path = os.path.join(base_dir, 'chats.db')
        
        print(f"Connecting to local SQLite database at: {db_path}")
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'

def add_column():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    column_name = "has_zarie"
    
    try:
        # Check if column already exists
        if db_type == 'postgres':
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='users' AND column_name=%s;
            """, (column_name,))
            if cursor.fetchone():
                print(f"Column '{column_name}' already exists in 'users' table.")
                conn.close()
                return
        else:
            # SQLite
            cursor.execute(f"PRAGMA table_info(users)")
            columns = [info[1] for info in cursor.fetchall()]
            if column_name in columns:
                print(f"Column '{column_name}' already exists in 'users' table.")
                conn.close()
                return

        print(f"Adding column '{column_name}' to 'users' table...")
        
        # Add column
        if db_type == 'postgres':
            # Postgres supports BOOLEAN
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} BOOLEAN DEFAULT FALSE")
        else:
            # SQLite supports BOOLEAN (as integer 0/1 usually), but we can use BOOLEAN keyword
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} BOOLEAN DEFAULT 0")
            
        # Update all rows to false (redundant with DEFAULT but requested)
        print("Setting all rows to FALSE...")
        if db_type == 'postgres':
            cursor.execute(f"UPDATE users SET {column_name} = FALSE")
        else:
            cursor.execute(f"UPDATE users SET {column_name} = 0")
            
        conn.commit()
        print("Successfully added column and updated rows.")
        
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    add_column()
