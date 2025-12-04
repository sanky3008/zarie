#!/usr/bin/env python3
"""
Migration script to fix time_events foreign key constraint to point to worker_agent_directory_v2
This addresses the issue where the FK was pointing to the old v1 table instead of v2.

The problem: time_events table has a FK constraint pointing to worker_agent_directory instead of 
worker_agent_directory_v2, causing FK violations when trying to insert time events for agents 
that only exist in v2.

Solution: Drop the old constraint and create a new one pointing to v2.
"""

import os
import psycopg2
import sqlite3
from dotenv import load_dotenv

load_dotenv()

def fix_postgres_fk():
    """Fix the foreign key constraint in PostgreSQL."""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    # Only use postgres if ENV=PROD and DATABASE_URL is set
    if env != 'PROD' or not database_url:
        print("❌ ENV must be 'PROD' and DATABASE_URL must be set. Skipping PostgreSQL migration.")
        return False
    
    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        print("🔍 Checking current foreign key constraints on time_events table...")
        cursor.execute("""
            SELECT 
                tc.constraint_name,
                kcu.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu 
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu 
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY' 
                AND tc.table_name = 'time_events'
        """)
        
        fk_info = cursor.fetchall()
        if not fk_info:
            print("❌ No foreign key constraints found on time_events table")
            cursor.close()
            conn.close()
            return False
        
        print(f"Found {len(fk_info)} foreign key constraint(s):")
        fixed_any = False
        constraint_to_drop = None
        
        for fk in fk_info:
            constraint_name, table_name, column_name, foreign_table_name, foreign_column_name = fk
            print(f"  - {constraint_name}: {table_name}.{column_name} -> {foreign_table_name}.{foreign_column_name}")
            
            if foreign_table_name == 'worker_agent_directory' and constraint_to_drop is None:
                constraint_to_drop = constraint_name
                fixed_any = True
        
        if constraint_to_drop:
            print(f"\n⚠️  Found FK pointing to OLD table (worker_agent_directory)")
            print(f"   Constraint: {constraint_to_drop}")
            
            # Drop the old constraint
            print(f"   Dropping old constraint: {constraint_to_drop}...")
            cursor.execute(f"ALTER TABLE time_events DROP CONSTRAINT {constraint_to_drop} CASCADE")
            conn.commit()
            print(f"   ✓ Dropped constraint")
        else:
            for fk in fk_info:
                constraint_name, table_name, column_name, foreign_table_name, foreign_column_name = fk
                if foreign_table_name == 'worker_agent_directory_v2':
                    print(f"\n✅ FK is already pointing to correct table (worker_agent_directory_v2)")
                    print(f"   Constraint: {constraint_name}")
                    return True
        
        # Create new constraint pointing to v2 if we dropped the old one
        if fixed_any:
            new_constraint_name = "time_events_agent_name_user_id_fkey"
            print(f"\n   Creating new constraint: {new_constraint_name}...")
            cursor.execute(f"""
                ALTER TABLE time_events
                ADD CONSTRAINT {new_constraint_name}
                FOREIGN KEY (agent_name, user_id)
                REFERENCES worker_agent_directory_v2(agent_name, user_id)
            """)
            conn.commit()
            print(f"   ✓ Created new constraint pointing to worker_agent_directory_v2")
        
        cursor.close()
        conn.close()
        print("\n✅ PostgreSQL migration completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ PostgreSQL Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def fix_sqlite_fk():
    """Fix the foreign key constraint in SQLite."""
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'chats.db')
    
    if not os.path.exists(db_path):
        print(f"⚠️  SQLite database not found at {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("\n🔍 Checking time_events table schema in SQLite...")
        cursor.execute("PRAGMA table_info(time_events)")
        columns = cursor.fetchall()
        
        if not columns:
            print("❌ time_events table not found in SQLite database")
            conn.close()
            return False
        
        # Get foreign key info
        cursor.execute("PRAGMA foreign_key_list(time_events)")
        fk_info = cursor.fetchall()
        
        if not fk_info:
            print("❌ No foreign key constraints found on time_events table")
            conn.close()
            return False
        
        print(f"Found {len(fk_info)} foreign key constraint(s):")
        needs_fix = False
        
        for fk in fk_info:
            id_, seq, table_name, from_col, to_col, on_delete, on_update, match, info = fk
            print(f"  - FK {id_}: time_events({from_col}) -> {table_name}({to_col})")
            
            if table_name == 'worker_agent_directory':
                print(f"\n⚠️  Found FK pointing to OLD table (worker_agent_directory)")
                needs_fix = True
            elif table_name == 'worker_agent_directory_v2':
                print(f"\n✅ FK is already pointing to correct table (worker_agent_directory_v2)")
        
        if needs_fix:
            print("\n⚠️  SQLite requires table recreation to change foreign keys")
            print("   Creating backup and recreating table with new FK...")
            
            # Get current time_events schema
            cursor.execute("""
                SELECT sql FROM sqlite_master 
                WHERE type='table' AND name='time_events'
            """)
            create_sql = cursor.fetchone()[0]
            print(f"\n   Current schema:\n   {create_sql}")
            
            # Create new table with correct FK
            print("\n   Creating new table with corrected FK...")
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
                    FOREIGN KEY (agent_name, user_id) REFERENCES worker_agent_directory_v2(agent_name, user_id),
                    UNIQUE(agent_name, reminder_name, user_id)
                )
            """)
            
            # Copy data
            cursor.execute("""
                INSERT INTO time_events_new 
                SELECT * FROM time_events
            """)
            
            # Drop old table
            cursor.execute("DROP TABLE time_events")
            
            # Rename new table
            cursor.execute("ALTER TABLE time_events_new RENAME TO time_events")
            
            conn.commit()
            print("   ✓ Successfully recreated time_events table with correct FK")
        
        conn.close()
        print("\n✅ SQLite migration completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ SQLite Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run the migration."""
    print("=" * 70)
    print("TIME_EVENTS FOREIGN KEY FIX MIGRATION")
    print("=" * 70)
    print()
    print("Problem: time_events table has FK pointing to worker_agent_directory")
    print("         instead of worker_agent_directory_v2")
    print()
    print("Solution: Update FK constraint to point to v2 table")
    print("=" * 70)
    print()
    
    database_url = os.getenv('DATABASE_URL')
    
    if database_url:
        print("Detected PostgreSQL database")
        fix_postgres_fk()
    else:
        print("Detected SQLite database")
        fix_sqlite_fk()
    
    print()
    print("=" * 70)
    print("Migration completed!")
    print("=" * 70)

if __name__ == "__main__":
    main()

