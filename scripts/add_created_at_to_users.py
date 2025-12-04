"""
Migration script to add created_at column to users table
Supports both SQLite (local) and PostgreSQL (Railway)
"""

import os
import sys
import sqlite3
from dotenv import load_dotenv

load_dotenv()


def migrate_postgres():
    """Migrate PostgreSQL database to add created_at column."""
    try:
        import psycopg2
        
        env = os.getenv('ENV', 'LOCAL').upper()
        database_url = os.getenv('DATABASE_URL')
        
        # Only use postgres if ENV=PROD and DATABASE_URL is set
        if env != 'PROD' or not database_url:
            print("⚠️  Skipping PostgreSQL: ENV must be 'PROD' and DATABASE_URL must be set")
            return True  # Not an error, just skipping
        
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        print("🔄 PostgreSQL: Checking if created_at column exists...")
        cursor.execute("""
            SELECT column_name, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'users' 
            AND column_name = 'created_at'
        """)
        result = cursor.fetchone()
        
        if result:
            print(f"✅ PostgreSQL: created_at column already exists (nullable: {result[1]}, default: {result[2]})")
            cursor.close()
            conn.close()
            return True
        
        print("🔄 PostgreSQL: Adding created_at column...")
        cursor.execute("""
            ALTER TABLE users 
            ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """)
        conn.commit()
        print("✅ PostgreSQL: Successfully added created_at column")
        
        # Display updated schema
        print("\n--- Updated users table schema (PostgreSQL) ---")
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'users'
            ORDER BY ordinal_position
        """)
        for row in cursor.fetchall():
            nullable = "NULL" if row[2] == 'YES' else "NOT NULL"
            default = f"DEFAULT {row[3]}" if row[3] else ""
            print(f"  {row[0]}: {row[1]} {nullable} {default}")
        
        cursor.close()
        conn.close()
        return True
        
    except ImportError:
        print("⚠️  psycopg2 not installed. Skipping PostgreSQL migration.")
        return True  # Not an error
    except Exception as e:
        print(f"❌ PostgreSQL Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def migrate_sqlite():
    """Migrate SQLite database to add created_at column."""
    try:
        # Locate the SQLite database
        # Path: scripts/ -> alpha-v0.1/ -> .. -> Donna/ -> chats.db
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 
            '..', 
            'chats.db'
        )
        
        if not os.path.exists(db_path):
            print(f"⚠️  SQLite database not found at {db_path}. Skipping SQLite migration.")
            return True  # Not an error
        
        print(f"🔄 SQLite: Connecting to {db_path}...")
        conn = sqlite3.connect(db_path, timeout=30.0)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='users'
        """)
        if not cursor.fetchone():
            print("❌ SQLite: Table 'users' not found")
            cursor.close()
            conn.close()
            return False
        
        print("🔄 SQLite: Checking if created_at column exists...")
        cursor.execute("PRAGMA table_info(users)")
        columns = cursor.fetchall()
        
        # Check if created_at already exists
        for col in columns:
            if col[1] == 'created_at':
                print(f"✅ SQLite: created_at column already exists")
                cursor.close()
                conn.close()
                return True
        
        print("🔄 SQLite: Adding created_at column...")
        # SQLite doesn't support CURRENT_TIMESTAMP as default when adding columns
        # We add the column as nullable, and the application code will set timestamps
        cursor.execute("""
            ALTER TABLE users 
            ADD COLUMN created_at TIMESTAMP
        """)
        conn.commit()
        print("✅ SQLite: Successfully added created_at column (nullable)")
        print("   Note: Existing users will have NULL for created_at")
        print("   Note: New users will get timestamps via application code")
        
        # Display updated schema
        print("\n--- Updated users table schema (SQLite) ---")
        cursor.execute("PRAGMA table_info(users)")
        for row in cursor.fetchall():
            nullable = "NULL" if not row[3] else "NOT NULL"
            default = f"DEFAULT {row[4]}" if row[4] else ""
            print(f"  {row[1]}: {row[2]} {nullable} {default}")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ SQLite Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run migrations for both database types."""
    print("\n" + "="*60)
    print("Users Table - Add created_at Column Migration")
    print("="*60 + "\n")
    
    database_url = os.getenv('DATABASE_URL')
    env = os.getenv('ENV', 'LOCAL').upper()
    
    postgres_success = True
    sqlite_success = True
    
    # Try PostgreSQL if ENV=PROD and DATABASE_URL is set
    if env == 'PROD' and database_url:
        print("📝 PostgreSQL migration:\n")
        postgres_success = migrate_postgres()
        print()
    else:
        print("📝 Skipping PostgreSQL (ENV is not PROD or DATABASE_URL not set)\n")
    
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
