
import os
import sqlite3
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def migrate_db():
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    print(f"Running migration for environment: {env}")

    if env == 'PROD' and database_url:
        print("Connecting to PostgreSQL database...")
        conn = psycopg2.connect(database_url)
        is_postgres = True
    else:
        print("Connecting to local SQLite database...")
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'chats.db')
        conn = sqlite3.connect(db_path)
        is_postgres = False

    cursor = conn.cursor()

    try:
        # 1. Add running_summary to worker_agent_directory_v2
        print("Adding running_summary column to worker_agent_directory_v2...")
        try:
            if is_postgres:
                cursor.execute("ALTER TABLE worker_agent_directory_v2 ADD COLUMN IF NOT EXISTS running_summary TEXT;")
            else:
                # SQLite doesn't support IF NOT EXISTS for columns in older versions, but let's try or catch error
                try:
                    cursor.execute("ALTER TABLE worker_agent_directory_v2 ADD COLUMN running_summary TEXT;")
                except sqlite3.OperationalError as e:
                    if "duplicate column name" in str(e):
                        print("Column running_summary already exists.")
                    else:
                        raise
        except Exception as e:
            print(f"Error adding running_summary: {e}")

        # 2. Add is_summarised to worker_agent_context
        print("Adding is_summarised column to worker_agent_context...")
        try:
            if is_postgres:
                cursor.execute("ALTER TABLE worker_agent_context ADD COLUMN IF NOT EXISTS is_summarised BOOLEAN DEFAULT FALSE;")
            else:
                 try:
                    cursor.execute("ALTER TABLE worker_agent_context ADD COLUMN is_summarised BOOLEAN DEFAULT 0;")
                 except sqlite3.OperationalError as e:
                    if "duplicate column name" in str(e):
                        print("Column is_summarised already exists.")
                    else:
                        raise
        except Exception as e:
            print(f"Error adding is_summarised: {e}")

        conn.commit()
        print("Migration completed successfully.")

    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    migrate_db()
