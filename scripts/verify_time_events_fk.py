#!/usr/bin/env python3
"""
Verification script to confirm that time_events FK constraint is correctly pointing to worker_agent_directory_v2
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def verify_postgres_fk():
    """Verify the foreign key constraint in PostgreSQL."""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    # Only use postgres if ENV=PROD and DATABASE_URL is set
    if env != 'PROD' or not database_url:
        print("❌ ENV must be 'PROD' and DATABASE_URL must be set")
        return False
    
    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        print("=" * 70)
        print("VERIFYING TIME_EVENTS FOREIGN KEY CONSTRAINT")
        print("=" * 70)
        
        # Check foreign key constraints using pg_catalog
        print("\n🔍 Checking foreign key constraints on time_events table...")
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
        
        print(f"\n✓ Found {len(fk_info)} foreign key constraint(s):")
        correct_fk = False
        
        for fk in fk_info:
            constraint_name, table_name, column_name, foreign_table_name, foreign_column_name = fk
            print(f"\n  Constraint: {constraint_name}")
            print(f"    time_events.{column_name} -> {foreign_table_name}.{foreign_column_name}")
            
            if foreign_table_name == 'worker_agent_directory_v2':
                print(f"    ✅ CORRECT - Points to worker_agent_directory_v2")
                correct_fk = True
            elif foreign_table_name == 'worker_agent_directory':
                print(f"    ❌ INCORRECT - Still points to old worker_agent_directory")
        
        # Check table row counts
        print("\n" + "-" * 70)
        print("Table statistics:")
        
        cursor.execute("SELECT COUNT(*) FROM worker_agent_directory")
        v1_count = cursor.fetchone()[0]
        print(f"  worker_agent_directory (v1):     {v1_count} rows")
        
        cursor.execute("SELECT COUNT(*) FROM worker_agent_directory_v2")
        v2_count = cursor.fetchone()[0]
        print(f"  worker_agent_directory_v2 (v2):  {v2_count} rows")
        
        cursor.execute("SELECT COUNT(*) FROM time_events")
        te_count = cursor.fetchone()[0]
        print(f"  time_events:                      {te_count} rows")
        
        # Try a test insert to verify FK works
        print("\n" + "-" * 70)
        print("Testing FK constraint with a sample query...")
        
        cursor.execute("""
            SELECT agent_name, user_id FROM worker_agent_directory_v2 LIMIT 1
        """)
        test_agent = cursor.fetchone()
        
        if test_agent:
            agent_name, user_id = test_agent
            print(f"  Found test agent: {agent_name} (user: {user_id})")
            
            # Try to insert a test time event (with ROLLBACK to not affect DB)
            try:
                cursor.execute("BEGIN")
                cursor.execute("""
                    INSERT INTO time_events 
                    (agent_name, user_id, reminder_name, next_trigger_timestamp, is_recurring, message, status)
                    VALUES (%s, %s, %s, NOW(), FALSE, 'TEST', 'ACTIVE')
                """, (agent_name, user_id, 'test_reminder_' + str(os.getpid())))
                print(f"  ✅ Test insert succeeded - FK constraint is working!")
                cursor.execute("ROLLBACK")
                test_passed = True
            except Exception as e:
                print(f"  ❌ Test insert failed: {e}")
                cursor.execute("ROLLBACK")
                test_passed = False
        else:
            print("  ⚠️  No test agent found in worker_agent_directory_v2")
            test_passed = None
        
        cursor.close()
        conn.close()
        
        print("\n" + "=" * 70)
        if correct_fk and (test_passed or test_passed is None):
            print("✅ VERIFICATION PASSED - FK constraint is correctly configured!")
            return True
        else:
            print("❌ VERIFICATION FAILED - FK constraint needs fixing")
            return False
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    verify_postgres_fk()

