import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    if env == 'PROD' and database_url:
        print("Connecting to Production Database (Postgres)...")
        import psycopg2
        conn = psycopg2.connect(database_url)
        return conn, 'postgres'
    else:
        print("Connecting to Local Database (SQLite)...")
        # Script is in zarie/scripts/
        # We want ../../chats.db relative to this script (i.e., in Donna/)
        # dirname(script) = zarie/scripts
        # dirname(dirname) = zarie
        # dirname(dirname(dirname)) = Donna
        
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(base_dir, 'chats.db')
        
        print(f"DB Path: {db_path}")
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'

def migrate_sqlite(conn):
    cursor = conn.cursor()
    
    print("Starting SQLite migration...")
    
    # Check if migration already happened by checking for slack_id column
    try:
        cursor.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'slack_id' in columns:
            print("Migration already applied (slack_id column exists).")
        else:
            # 1. Create new users table
            print("Creating new users table...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id TEXT UNIQUE,
                    slack_id TEXT UNIQUE,
                    name TEXT,
                    telegram_username TEXT,
                    slack_username TEXT,
                    created_at TIMESTAMP,
                    has_zarie BOOLEAN DEFAULT 0
                )
            """)
            
            # 2. Copy data
            print("Copying users data...")
            cursor.execute("""
                INSERT INTO users_new (id, telegram_id, name, telegram_username, created_at, has_zarie)
                SELECT id, telegram_id, name, telegram_username, created_at, has_zarie FROM users
            """)
            
            # 3. Swap tables
            print("Swapping users tables...")
            cursor.execute("DROP TABLE users")
            cursor.execute("ALTER TABLE users_new RENAME TO users")
            cursor.execute("CREATE INDEX idx_users_telegram_id ON users(telegram_id)")
            cursor.execute("CREATE INDEX idx_users_slack_id ON users(slack_id)")
    except Exception as e:
        print(f"Error during users table migration: {e}")
        # If users table doesn't exist, we can't do much.
        return
    
    # 4. Migrate other tables to use internal ID
    tables_to_migrate = ['chats', 'chats_context', 'reflections', 'worker_agent_directory', 'time_events']
    
    for table in tables_to_migrate:
        print(f"Migrating {table}...")
        try:
            # Check if table exists
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if not cursor.fetchone():
                print(f"Table {table} does not exist, skipping.")
                continue

            cursor.execute(f"SELECT rowid, user_id FROM {table}")
            records = cursor.fetchall()
            
            for rowid, old_user_id in records:
                # Try to find user by telegram_id
                cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (old_user_id,))
                result = cursor.fetchone()
                
                if result:
                    internal_id = str(result[0])
                    if internal_id != old_user_id:
                        try:
                            cursor.execute(f"UPDATE {table} SET user_id = ? WHERE rowid = ?", (internal_id, rowid))
                        except sqlite3.IntegrityError as e:
                            print(f"Skipping duplicate/error for {table} row {rowid}: {e}")
        except sqlite3.OperationalError as e:
            print(f"Error processing table {table}: {e}")

    # 5. Add platform column to time_events
    print("Adding platform column to time_events...")
    try:
        cursor.execute("ALTER TABLE time_events ADD COLUMN platform TEXT DEFAULT 'telegram'")
    except sqlite3.OperationalError:
        print("Column platform might already exist in time_events")

    conn.commit()
    print("SQLite migration completed.")

def migrate_postgres(conn):
    cursor = conn.cursor()
    print("Starting Postgres migration...")
    
    # 1. Alter users table
    print("Altering users table...")
    cursor.execute("ALTER TABLE users ALTER COLUMN telegram_id DROP NOT NULL")
    cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS slack_id TEXT UNIQUE")
    cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS slack_username TEXT")
    
    # 2. Migrate data in other tables
    tables_to_migrate = ['chats', 'chats_context', 'reflections', 'worker_agent_directory', 'time_events']
    
    for table in tables_to_migrate:
        print(f"Migrating {table}...")
        query = f"""
            UPDATE {table}
            SET user_id = users.id::TEXT
            FROM users
            WHERE {table}.user_id = users.telegram_id
        """
        cursor.execute(query)
        
    # 3. Add platform to time_events
    print("Adding platform to time_events...")
    cursor.execute("ALTER TABLE time_events ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'telegram'")
    
    conn.commit()
    print("Postgres migration completed.")

if __name__ == "__main__":
    conn, db_type = get_db_connection()
    try:
        if db_type == 'sqlite':
            migrate_sqlite(conn)
        else:
            migrate_postgres(conn)
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
    finally:
        conn.close()
