"""
Migration script to make the 'purpose' column nullable in worker_agent_directory_v2 table.

This script handles the production migration for both PostgreSQL and SQLite databases.
It safely removes the NOT NULL constraint from the purpose column.

Usage:
    python scripts/make_purpose_nullable.py

For PostgreSQL, ensure DATABASE_URL environment variable is set.
For SQLite, ensure the database path is correct.
"""

import os
import sys
import sqlite3
from dotenv import load_dotenv

load_dotenv()


def migrate_postgres():
    """Migrate PostgreSQL database to make purpose column nullable."""
    try:
        import psycopg2
        
        env = os.getenv('ENV', 'LOCAL').upper()
        database_url = os.getenv('DATABASE_URL')
        
        # Only use postgres if ENV=PROD and DATABASE_URL is set
        if env != 'PROD' or not database_url:
            print("❌ ERROR: ENV must be 'PROD' and DATABASE_URL environment variable must be set")
            return False
        
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        print("🔄 PostgreSQL: Checking if purpose column exists...")
        cursor.execute("""
            SELECT column_name, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'worker_agent_directory_v2' 
            AND column_name = 'purpose'
        """)
        result = cursor.fetchone()
        
        if not result:
            print("❌ Table worker_agent_directory_v2 not found")
            cursor.close()
            conn.close()
            return False
        
        column_name, is_nullable = result
        
        if is_nullable == 'YES':
            print("✅ PostgreSQL: purpose column is already nullable")
            cursor.close()
            conn.close()
            return True
        
        print("🔄 PostgreSQL: Making purpose column nullable...")
        cursor.execute("""
            ALTER TABLE worker_agent_directory_v2 
            ALTER COLUMN purpose DROP NOT NULL
        """)
        conn.commit()
        print("✅ PostgreSQL: Successfully made purpose column nullable")
        
        cursor.close()
        conn.close()
        return True
        
    except ImportError:
        print("⚠️  psycopg2 not installed. Skipping PostgreSQL migration.")
        return False
    except Exception as e:
        print(f"❌ PostgreSQL Error: {e}")
        return False


def migrate_sqlite():
    """Migrate SQLite database to make purpose column nullable."""
    try:
        # Locate the SQLite database
        # It should be at the root of the project
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
            'chats.db'
        )
        
        if not os.path.exists(db_path):
            print(f"⚠️  SQLite database not found at {db_path}. Skipping SQLite migration.")
            return True
        
        print(f"🔄 SQLite: Connecting to {db_path}...")
        conn = sqlite3.connect(db_path, timeout=30.0)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='worker_agent_directory_v2'
        """)
        if not cursor.fetchone():
            print("❌ SQLite: Table worker_agent_directory_v2 not found")
            cursor.close()
            conn.close()
            return False
        
        print("🔄 SQLite: Checking table schema...")
        cursor.execute("PRAGMA table_info(worker_agent_directory_v2)")
        columns = cursor.fetchall()
        
        purpose_column = None
        for col in columns:
            if col[1] == 'purpose':
                purpose_column = col
                break
        
        if not purpose_column:
            print("❌ SQLite: purpose column not found")
            cursor.close()
            conn.close()
            return False
        
        # SQLite column format: (cid, name, type, notnull, dflt_value, pk)
        notnull = purpose_column[3]
        
        if notnull == 0:
            print("✅ SQLite: purpose column is already nullable")
            cursor.close()
            conn.close()
            return True
        
        print("🔄 SQLite: Recreating table with nullable purpose column...")
        
        # SQLite doesn't support ALTER COLUMN, so we need to recreate the table
        cursor.execute("BEGIN TRANSACTION")
        
        # Create temporary table with nullable purpose
        cursor.execute("""
            CREATE TABLE worker_agent_directory_v2_temp (
                agent_name TEXT NOT NULL,
                user_id TEXT NOT NULL,
                purpose TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (agent_name, user_id)
            )
        """)
        
        # Copy data
        cursor.execute("""
            INSERT INTO worker_agent_directory_v2_temp 
            SELECT agent_name, user_id, purpose, created_at, updated_at 
            FROM worker_agent_directory_v2
        """)
        
        # Drop old table
        cursor.execute("DROP TABLE worker_agent_directory_v2")
        
        # Rename temporary table
        cursor.execute("ALTER TABLE worker_agent_directory_v2_temp RENAME TO worker_agent_directory_v2")
        
        conn.commit()
        print("✅ SQLite: Successfully made purpose column nullable")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ SQLite Error: {e}")
        return False


def main():
    """Run migrations for both database types."""
    print("\n" + "="*60)
    print("Worker Agent Directory - Make Purpose Column Nullable")
    print("="*60 + "\n")
    
    database_url = os.getenv('DATABASE_URL')
    
    postgres_success = True
    sqlite_success = True
    
    # Try PostgreSQL if DATABASE_URL is set
    if database_url:
        print("📝 PostgreSQL migration:\n")
        postgres_success = migrate_postgres()
        print()
    
    # Try SQLite (usually for local development)
    print("📝 SQLite migration:\n")
    sqlite_success = migrate_sqlite()
    print()
    
    # Summary
    print("="*60)
    if postgres_success and sqlite_success:
        print("✅ All migrations completed successfully!")
        print("="*60 + "\n")
        return 0
    else:
        print("⚠️  Some migrations failed or were skipped")
        print("="*60 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())

