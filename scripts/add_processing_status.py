#!/usr/bin/env python3
"""
Migration script to add 'PROCESSING' status to time_events table
Supports both SQLite (local) and PostgreSQL (Railway)
"""
import os
import sys

def get_db_connection():
    """Get database connection - respects ENV variable for safety"""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_PUBLIC_URL')
    
    # Only use postgres if ENV=PROD and DATABASE_URL is set
    if env == 'PROD' and database_url:
        try:
            import psycopg2
            conn = psycopg2.connect(database_url)
            return conn, 'postgres'
        except ImportError:
            print("❌ psycopg2 not installed. Install with: pip install psycopg2-binary")
            sys.exit(1)
    else:
        import sqlite3
        # Use absolute path for local database
        db_path = '/Users/sankalpphadnis/Documents/Donna/chats.db'
        if not os.path.exists(db_path):
            print(f"❌ Database not found at: {db_path}")
            sys.exit(1)
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'

def migrate_postgres(conn):
    """Migrate PostgreSQL database"""
    cursor = conn.cursor()
    
    try:
        print("PostgreSQL migration starting...")
        
        # Check if PROCESSING is already in the constraint
        cursor.execute("""
            SELECT con.conname, pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            INNER JOIN pg_class rel ON rel.oid = con.conrelid
            WHERE rel.relname = 'time_events' AND con.contype = 'c'
        """)
        
        constraints = cursor.fetchall()
        processing_exists = any('PROCESSING' in str(c[1]) for c in constraints)
        
        if processing_exists:
            print("✓ 'PROCESSING' status already exists in constraint")
            return True
        
        print("Adding 'PROCESSING' status to check constraint...")
        
        # Drop old constraint and add new one
        cursor.execute("""
            ALTER TABLE time_events 
            DROP CONSTRAINT IF EXISTS time_events_status_check
        """)
        
        cursor.execute("""
            ALTER TABLE time_events 
            ADD CONSTRAINT time_events_status_check 
            CHECK (status IN ('ACTIVE', 'INACTIVE', 'DISABLED', 'PROCESSING'))
        """)
        
        conn.commit()
        print("✅ PostgreSQL migration completed successfully!")
        
        # Verify the change
        cursor.execute("""
            SELECT pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            INNER JOIN pg_class rel ON rel.oid = con.conrelid
            WHERE rel.relname = 'time_events' 
            AND con.conname = 'time_events_status_check'
        """)
        
        constraint_def = cursor.fetchone()
        if constraint_def:
            print(f"✓ New constraint: {constraint_def[0]}")
        
        return True
        
    except Exception as e:
        print(f"❌ PostgreSQL migration failed: {e}")
        conn.rollback()
        return False

def migrate_sqlite(conn):
    """Migrate SQLite database"""
    cursor = conn.cursor()
    
    try:
        print("SQLite migration starting...")
        
        # Check if PROCESSING already exists by attempting to insert a test row
        cursor.execute("SELECT MAX(id) FROM time_events")
        max_id = cursor.fetchone()[0] or 0
        test_id = max_id + 999999  # Use a very high ID to avoid conflicts
        
        try:
            cursor.execute("""
                INSERT INTO time_events 
                (id, agent_name, reminder_name, user_id, next_trigger_timestamp, 
                 is_recurring, message, status)
                VALUES (?, 'test_agent', 'test_reminder', 'test_user', 
                        datetime('now'), 0, 'test', 'PROCESSING')
            """, (test_id,))
            
            # If we got here, PROCESSING is already allowed
            cursor.execute("DELETE FROM time_events WHERE id = ?", (test_id,))
            conn.commit()
            print("✓ 'PROCESSING' status already exists in constraint")
            return True
            
        except Exception:
            # PROCESSING not allowed, need to migrate
            conn.rollback()
            pass
        
        print("Creating new table with updated constraint...")
        
        # Step 1: Create new table with updated constraint
        cursor.execute("""
            CREATE TABLE time_events_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                agent_name TEXT NOT NULL,
                reminder_name TEXT NOT NULL,
                user_id TEXT NOT NULL,
                next_trigger_timestamp TIMESTAMP NOT NULL,
                is_recurring BOOLEAN DEFAULT 0,
                recurrence_rule TEXT,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'INACTIVE', 'DISABLED', 'PROCESSING')),
                FOREIGN KEY (agent_name, user_id) REFERENCES worker_agent_directory(agent_name, user_id),
                UNIQUE(agent_name, reminder_name, user_id)
            )
        """)
        
        print("Copying data from old table...")
        
        # Step 2: Copy all data from old table to new table
        cursor.execute("""
            INSERT INTO time_events_new 
            (id, created_at, agent_name, reminder_name, user_id, 
             next_trigger_timestamp, is_recurring, recurrence_rule, message, status)
            SELECT id, created_at, agent_name, reminder_name, user_id,
                   next_trigger_timestamp, is_recurring, recurrence_rule, message, status
            FROM time_events
        """)
        
        rows_copied = cursor.rowcount
        print(f"✓ Copied {rows_copied} rows")
        
        print("Dropping old table...")
        
        # Step 3: Drop old table
        cursor.execute("DROP TABLE time_events")
        
        print("Renaming new table...")
        
        # Step 4: Rename new table to original name
        cursor.execute("ALTER TABLE time_events_new RENAME TO time_events")
        
        print("Recreating indices...")
        
        # Step 5: Recreate indices
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
        print("✅ SQLite migration completed successfully!")
        
        # Verify the change
        cursor.execute("SELECT COUNT(*) FROM time_events")
        final_count = cursor.fetchone()[0]
        print(f"✓ Table has {final_count} rows")
        
        return True
        
    except Exception as e:
        print(f"❌ SQLite migration failed: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return False

def main():
    """Main migration function"""
    print("=" * 60)
    print("Migration: Add 'PROCESSING' Status to time_events Table")
    print("=" * 60)
    print()
    
    try:
        conn, db_type = get_db_connection()
        print(f"Connected to {db_type.upper()} database")
        print()
        
        if db_type == 'postgres':
            success = migrate_postgres(conn)
        else:
            success = migrate_sqlite(conn)
        
        conn.close()
        
        if success:
            print()
            print("=" * 60)
            print("✅ MIGRATION SUCCESSFUL")
            print("=" * 60)
            print()
            print("The time_events table now accepts 'PROCESSING' status.")
            print("The scheduler can now properly lock events during processing.")
            sys.exit(0)
        else:
            print()
            print("=" * 60)
            print("❌ MIGRATION FAILED")
            print("=" * 60)
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

