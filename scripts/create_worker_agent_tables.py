"""
Migration script to create worker_agent_directory and time_events tables
Supports both SQLite (local) and PostgreSQL (Railway)
"""
import os
from datetime import datetime

def get_db_connection():
    """Get database connection - respects ENV variable for safety"""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_PUBLIC_URL')
    
    # Only use postgres if ENV=PROD and DATABASE_URL is set
    if env == 'PROD' and database_url:
        import psycopg2
        conn = psycopg2.connect(database_url)
        return conn, 'postgres'
    else:
        import sqlite3
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'chats.db')
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'

def create_tables():
    """Create worker_agent_directory and time_events tables"""
    
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    print(f"Connected to {db_type.upper()} database")
    
    try:
        # Create worker_agent_directory table
        print("Creating worker_agent_directory table...")
        if db_type == 'postgres':
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS worker_agent_directory (
                    id SERIAL PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    purpose TEXT,
                    context TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(agent_name, user_id)
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS worker_agent_directory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    purpose TEXT,
                    context TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(agent_name, user_id)
                )
            """)
        
        # Create time_events table
        print("Creating time_events table...")
        if db_type == 'postgres':
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS time_events (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    agent_name TEXT NOT NULL,
                    reminder_name TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    next_trigger_timestamp TIMESTAMP NOT NULL,
                    is_recurring BOOLEAN DEFAULT FALSE,
                    recurrence_rule TEXT,
                    message TEXT NOT NULL,
                    status TEXT DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'INACTIVE', 'DISABLED')),
                    FOREIGN KEY (agent_name, user_id) REFERENCES worker_agent_directory(agent_name, user_id),
                    UNIQUE(agent_name, reminder_name, user_id)
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS time_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    agent_name TEXT NOT NULL,
                    reminder_name TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    next_trigger_timestamp TIMESTAMP NOT NULL,
                    is_recurring BOOLEAN DEFAULT 0,
                    recurrence_rule TEXT,
                    message TEXT NOT NULL,
                    status TEXT DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'INACTIVE', 'DISABLED')),
                    FOREIGN KEY (agent_name, user_id) REFERENCES worker_agent_directory(agent_name, user_id),
                    UNIQUE(agent_name, reminder_name, user_id)
                )
            """)
        
        # Create indices for better query performance
        print("Creating indices...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_worker_agent_user 
            ON worker_agent_directory(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_time_events_trigger 
            ON time_events(next_trigger_timestamp, status)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_time_events_user 
            ON time_events(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_time_events_agent 
            ON time_events(agent_name, user_id)
        """)
        
        conn.commit()
        print("\n✅ Tables created successfully!")
        
        # Display table info
        if db_type == 'postgres':
            print("\n--- worker_agent_directory schema ---")
            cursor.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'worker_agent_directory'
                ORDER BY ordinal_position
            """)
            for row in cursor.fetchall():
                print(f"  {row[0]}: {row[1]}")
            
            print("\n--- time_events schema ---")
            cursor.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'time_events'
                ORDER BY ordinal_position
            """)
            for row in cursor.fetchall():
                print(f"  {row[0]}: {row[1]}")
        else:
            print("\n--- worker_agent_directory schema ---")
            cursor.execute("PRAGMA table_info(worker_agent_directory)")
            for row in cursor.fetchall():
                print(f"  {row[1]}: {row[2]}")
            
            print("\n--- time_events schema ---")
            cursor.execute("PRAGMA table_info(time_events)")
            for row in cursor.fetchall():
                print(f"  {row[1]}: {row[2]}")
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    print("Migration Script: Creating Worker Agent Tables")
    print("Supports both SQLite (local) and PostgreSQL (Railway)")
    print()
    create_tables()

