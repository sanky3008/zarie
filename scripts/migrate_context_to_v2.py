#!/usr/bin/env python3
"""
Migration script to convert context from JSON blob format to structured v2 tables.

This script:
1. Reads from old tables (chats, worker_agent_directory)
2. Parses JSON blob contexts
3. Writes individual message rows to new tables (chats_context, worker_agent_directory_v2, worker_agent_context)
4. Works for both SQLite (local) and PostgreSQL (Railway)

Usage:
    python migrate_context_to_v2.py [--dry-run] [--db-path PATH]
"""

import sys
import os
import json
import argparse
from datetime import datetime

# Add parent directory to path to import project modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def create_v2_tables(pool, db_type, sqlite_conn, sqlite_lock):
    """Create v2 tables if they don't exist."""
    print("\n" + "="*70)
    print("CREATING V2 TABLES (if not exist)")
    print("="*70)
    
    if db_type == 'postgres':
        conn = pool.getconn()
        try:
            with conn.cursor() as cursor:
                # Create chats_context table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chats_context (
                        user_id TEXT NOT NULL,
                        message_sequence SERIAL NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT,
                        tool_calls TEXT,
                        tool_call_id TEXT,
                        tool_name TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (user_id, message_sequence)
                    )
                """)
                print("  ✓ Created/verified chats_context table")
                
                # Create worker_agent_directory_v2 table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS worker_agent_directory_v2 (
                        agent_name TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        purpose TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (agent_name, user_id)
                    )
                """)
                print("  ✓ Created/verified worker_agent_directory_v2 table")
                
                # Create worker_agent_context table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS worker_agent_context (
                        agent_name TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        message_sequence SERIAL NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT,
                        tool_calls TEXT,
                        tool_call_id TEXT,
                        tool_name TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (agent_name, user_id, message_sequence),
                        FOREIGN KEY (agent_name, user_id) REFERENCES worker_agent_directory_v2(agent_name, user_id) ON DELETE CASCADE
                    )
                """)
                print("  ✓ Created/verified worker_agent_context table")
                
                conn.commit()
                print("\n✅ All v2 tables ready\n")
                
        finally:
            pool.putconn(conn)
    
    else:  # SQLite
        with sqlite_lock:
            cursor = sqlite_conn.cursor()
            
            # Create chats_context table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chats_context (
                    user_id TEXT NOT NULL,
                    message_sequence INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT,
                    tool_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, message_sequence)
                )
            """)
            print("  ✓ Created/verified chats_context table")
            
            # Create worker_agent_directory_v2 table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS worker_agent_directory_v2 (
                    agent_name TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    purpose TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (agent_name, user_id)
                )
            """)
            print("  ✓ Created/verified worker_agent_directory_v2 table")
            
            # Create worker_agent_context table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS worker_agent_context (
                    agent_name TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    message_sequence INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT,
                    tool_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (agent_name, user_id, message_sequence),
                    FOREIGN KEY (agent_name, user_id) REFERENCES worker_agent_directory_v2(agent_name, user_id) ON DELETE CASCADE
                )
            """)
            print("  ✓ Created/verified worker_agent_context table")
            
            sqlite_conn.commit()
            print("\n✅ All v2 tables ready\n")

def migrate_main_agent_context(pool, db_type, sqlite_conn, sqlite_lock, RealDictCursor, dry_run=False):
    """Migrate main agent context from chats to chats_context."""
    print("\n" + "="*70)
    print("MIGRATING MAIN AGENT CONTEXT (chats -> chats_context)")
    print("="*70)
    
    migrated_users = 0
    migrated_messages = 0
    skipped_users = 0
    errors = 0
    
    try:
        if db_type == 'postgres':
            conn = pool.getconn()
            try:
                # Fetch all users with context from old table
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SELECT user_id, context FROM chats")
                    rows = cursor.fetchall()
                    
                    print(f"Found {len(rows)} users in old chats table")
                    
                    for row in rows:
                        user_id = row['user_id']
                        context_json = row['context']
                        
                        try:
                            # Parse JSON blob
                            messages = json.loads(context_json) if context_json else []
                            
                            if not messages:
                                print(f"  Skipping {user_id}: No messages")
                                skipped_users += 1
                                continue
                            
                            # Get last migrated message to determine starting point
                            cursor.execute("""
                                SELECT message_sequence, role, content, tool_calls, tool_call_id, tool_name
                                FROM chats_context 
                                WHERE user_id = %s 
                                ORDER BY message_sequence DESC 
                                LIMIT 1
                            """, (user_id,))
                            last_migrated = cursor.fetchone()
                            
                            start_index = 0
                            if last_migrated:
                                last_seq = last_migrated['message_sequence']
                                # Verify the last message matches
                                if last_seq <= len(messages):
                                    last_msg = messages[last_seq - 1]
                                    # Compare key fields
                                    if (last_msg.get('role') == last_migrated['role'] and
                                        last_msg.get('content') == last_migrated['content']):
                                        start_index = last_seq
                                    else:
                                        print(f"  ⚠ Warning: Last message mismatch for {user_id}, re-migrating from start")
                                        # Delete existing to re-migrate
                                        if not dry_run:
                                            cursor.execute("DELETE FROM chats_context WHERE user_id = %s", (user_id,))
                                else:
                                    print(f"  ⚠ Warning: More messages in v2 than source for {user_id}, re-migrating")
                                    if not dry_run:
                                        cursor.execute("DELETE FROM chats_context WHERE user_id = %s", (user_id,))
                            
                            # Get messages to migrate (only new ones)
                            new_messages = messages[start_index:]
                            
                            if not new_messages:
                                print(f"  ✓ {user_id}: Already up-to-date ({start_index} messages)")
                                skipped_users += 1
                                continue
                            
                            # Only print "resuming" message if there are new messages
                            if start_index > 0:
                                print(f"  Resuming {user_id}: Already migrated {start_index} messages, adding {len(new_messages)} new")
                            
                            if dry_run:
                                print(f"  [DRY RUN] Would migrate {len(new_messages)} new messages for {user_id} (total: {len(messages)})")
                                migrated_users += 1
                                migrated_messages += len(new_messages)
                                continue
                            
                            # Insert each new message with sequence
                            for idx, msg in enumerate(new_messages, start=start_index + 1):
                                role = msg.get('role')
                                content = msg.get('content')
                                tool_calls = json.dumps(msg['tool_calls']) if 'tool_calls' in msg else None
                                tool_call_id = msg.get('tool_call_id')
                                tool_name = msg.get('tool_name')
                                
                                cursor.execute("""
                                    INSERT INTO chats_context 
                                    (user_id, message_sequence, role, content, tool_calls, tool_call_id, tool_name)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """, (user_id, idx, role, content, tool_calls, tool_call_id, tool_name))
                            
                            print(f"  ✓ Migrated {len(new_messages)} new messages for {user_id} (total: {start_index + len(new_messages)})")
                            migrated_users += 1
                            migrated_messages += len(new_messages)
                            
                        except Exception as e:
                            print(f"  ✗ Error migrating {user_id}: {e}")
                            errors += 1
                            continue
                    
                    if not dry_run:
                        conn.commit()
                        print("\n✓ PostgreSQL migration committed")
                    
            finally:
                pool.putconn(conn)
                
        else:  # SQLite
            with sqlite_lock:
                cursor = sqlite_conn.cursor()
                
                # Fetch all users with context from old table
                cursor.execute("SELECT user_id, context FROM chats")
                rows = cursor.fetchall()
                
                print(f"Found {len(rows)} users in old chats table")
                
                for row in rows:
                    user_id = row[0]
                    context_json = row[1]
                    
                    try:
                        # Parse JSON blob
                        messages = json.loads(context_json) if context_json else []
                        
                        if not messages:
                            print(f"  Skipping {user_id}: No messages")
                            skipped_users += 1
                            continue
                        
                        # Get last migrated message to determine starting point
                        cursor.execute("""
                            SELECT message_sequence, role, content, tool_calls, tool_call_id, tool_name
                            FROM chats_context 
                            WHERE user_id = ? 
                            ORDER BY message_sequence DESC 
                            LIMIT 1
                        """, (user_id,))
                        last_migrated = cursor.fetchone()
                        
                        start_index = 0
                        if last_migrated:
                            last_seq = last_migrated[0]
                            last_role = last_migrated[1]
                            last_content = last_migrated[2]
                            # Verify the last message matches
                            if last_seq <= len(messages):
                                last_msg = messages[last_seq - 1]
                                # Compare key fields
                                if (last_msg.get('role') == last_role and
                                    last_msg.get('content') == last_content):
                                    start_index = last_seq
                                else:
                                    print(f"  ⚠ Warning: Last message mismatch for {user_id}, re-migrating from start")
                                    # Delete existing to re-migrate
                                    if not dry_run:
                                        cursor.execute("DELETE FROM chats_context WHERE user_id = ?", (user_id,))
                            else:
                                print(f"  ⚠ Warning: More messages in v2 than source for {user_id}, re-migrating")
                                if not dry_run:
                                    cursor.execute("DELETE FROM chats_context WHERE user_id = ?", (user_id,))
                        
                        # Get messages to migrate (only new ones)
                        new_messages = messages[start_index:]
                        
                        if not new_messages:
                            print(f"  ✓ {user_id}: Already up-to-date ({start_index} messages)")
                            skipped_users += 1
                            continue
                        
                        # Only print "resuming" message if there are new messages
                        if start_index > 0:
                            print(f"  Resuming {user_id}: Already migrated {start_index} messages, adding {len(new_messages)} new")
                        
                        if dry_run:
                            print(f"  [DRY RUN] Would migrate {len(new_messages)} new messages for {user_id} (total: {len(messages)})")
                            migrated_users += 1
                            migrated_messages += len(new_messages)
                            continue
                        
                        # Insert each new message with sequence
                        for idx, msg in enumerate(new_messages, start=start_index + 1):
                            role = msg.get('role')
                            content = msg.get('content')
                            tool_calls = json.dumps(msg['tool_calls']) if 'tool_calls' in msg else None
                            tool_call_id = msg.get('tool_call_id')
                            tool_name = msg.get('tool_name')
                            
                            cursor.execute("""
                                INSERT INTO chats_context 
                                (user_id, message_sequence, role, content, tool_calls, tool_call_id, tool_name)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (user_id, idx, role, content, tool_calls, tool_call_id, tool_name))
                        
                        print(f"  ✓ Migrated {len(new_messages)} new messages for {user_id} (total: {start_index + len(new_messages)})")
                        migrated_users += 1
                        migrated_messages += len(new_messages)
                        
                    except Exception as e:
                        print(f"  ✗ Error migrating {user_id}: {e}")
                        errors += 1
                        continue
                
                if not dry_run:
                    sqlite_conn.commit()
                    print("\n✓ SQLite migration committed")
    
    except Exception as e:
        print(f"\n✗ Fatal error during main agent migration: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print(f"\nMain Agent Migration Summary:")
    print(f"  Users migrated: {migrated_users}")
    print(f"  Messages migrated: {migrated_messages}")
    print(f"  Users skipped: {skipped_users}")
    print(f"  Errors: {errors}")
    
    return errors == 0


def migrate_worker_agent_context(pool, db_type, sqlite_conn, sqlite_lock, RealDictCursor, dry_run=False):
    """Migrate worker agent context from worker_agent_directory to v2 tables."""
    print("\n" + "="*70)
    print("MIGRATING WORKER AGENT CONTEXT (worker_agent_directory -> v2)")
    print("="*70)
    
    migrated_agents = 0
    migrated_messages = 0
    skipped_agents = 0
    errors = 0
    
    try:
        if db_type == 'postgres':
            conn = pool.getconn()
            try:
                # Fetch all agents with context from old table
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("""
                        SELECT agent_name, user_id, purpose, context, created_at, updated_at 
                        FROM worker_agent_directory
                    """)
                    rows = cursor.fetchall()
                    
                    print(f"Found {len(rows)} worker agents in old table")
                    
                    for row in rows:
                        agent_name = row['agent_name']
                        user_id = row['user_id']
                        purpose = row['purpose']
                        context_json = row['context']
                        created_at = row['created_at']
                        updated_at = row['updated_at']
                        
                        try:
                            # Parse JSON blob
                            messages = json.loads(context_json) if context_json else []
                            
                            # Check if agent exists in directory_v2
                            cursor.execute("""
                                SELECT 1 FROM worker_agent_directory_v2 
                                WHERE agent_name = %s AND user_id = %s
                            """, (agent_name, user_id))
                            agent_exists = cursor.fetchone()
                            
                            # Get last migrated message if agent exists
                            start_index = 0
                            if agent_exists:
                                cursor.execute("""
                                    SELECT message_sequence, role, content
                                    FROM worker_agent_context 
                                    WHERE agent_name = %s AND user_id = %s 
                                    ORDER BY message_sequence DESC 
                                    LIMIT 1
                                """, (agent_name, user_id))
                                last_migrated = cursor.fetchone()
                                
                                if last_migrated:
                                    last_seq = last_migrated['message_sequence']
                                    # Verify the last message matches
                                    if last_seq <= len(messages):
                                        last_msg = messages[last_seq - 1]
                                        # Compare key fields
                                        if (last_msg.get('role') == last_migrated['role'] and
                                            last_msg.get('content') == last_migrated['content']):
                                            start_index = last_seq
                                        else:
                                            print(f"  ⚠ Warning: Last message mismatch for {agent_name} ({user_id}), re-migrating")
                                            if not dry_run:
                                                cursor.execute("DELETE FROM worker_agent_context WHERE agent_name = %s AND user_id = %s", (agent_name, user_id))
                                    else:
                                        print(f"  ⚠ Warning: More messages in v2 than source for {agent_name} ({user_id}), re-migrating")
                                        if not dry_run:
                                            cursor.execute("DELETE FROM worker_agent_context WHERE agent_name = %s AND user_id = %s", (agent_name, user_id))
                            
                            # Get messages to migrate (only new ones)
                            new_messages = messages[start_index:]
                            
                            if not new_messages and agent_exists:
                                print(f"  ✓ {agent_name} ({user_id}): Already up-to-date ({start_index} messages)")
                                skipped_agents += 1
                                continue
                            
                            # Only print "resuming" message if there are new messages
                            if start_index > 0 and new_messages:
                                print(f"  Resuming {agent_name} ({user_id}): Already migrated {start_index} messages, adding {len(new_messages)} new")
                            
                            if dry_run:
                                msg_info = f"{len(new_messages)} new messages" if agent_exists else f"{len(messages)} messages"
                                print(f"  [DRY RUN] Would migrate {agent_name} ({user_id}) with {msg_info}")
                                migrated_agents += 1
                                migrated_messages += len(new_messages) if agent_exists else len(messages)
                                continue
                            
                            # Insert into directory_v2 if not exists
                            if not agent_exists:
                                cursor.execute("""
                                    INSERT INTO worker_agent_directory_v2 
                                    (agent_name, user_id, purpose, created_at, updated_at)
                                    VALUES (%s, %s, %s, %s, %s)
                                """, (agent_name, user_id, purpose, created_at, updated_at))
                            
                            # Insert each new message with sequence
                            for idx, msg in enumerate(new_messages, start=start_index + 1):
                                role = msg.get('role')
                                content = msg.get('content')
                                tool_calls = json.dumps(msg['tool_calls']) if 'tool_calls' in msg else None
                                tool_call_id = msg.get('tool_call_id')
                                tool_name = msg.get('tool_name')
                                
                                cursor.execute("""
                                    INSERT INTO worker_agent_context 
                                    (agent_name, user_id, message_sequence, role, content, tool_calls, tool_call_id, tool_name)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                """, (agent_name, user_id, idx, role, content, tool_calls, tool_call_id, tool_name))
                            
                            print(f"  ✓ Migrated {agent_name} ({user_id}) with {len(new_messages)} new messages (total: {start_index + len(new_messages)})")
                            migrated_agents += 1
                            migrated_messages += len(new_messages)
                            
                        except Exception as e:
                            print(f"  ✗ Error migrating {agent_name} ({user_id}): {e}")
                            errors += 1
                            continue
                    
                    if not dry_run:
                        conn.commit()
                        print("\n✓ PostgreSQL migration committed")
                    
            finally:
                pool.putconn(conn)
                
        else:  # SQLite
            with sqlite_lock:
                cursor = sqlite_conn.cursor()
                
                # Fetch all agents with context from old table
                cursor.execute("""
                    SELECT agent_name, user_id, purpose, context, created_at, updated_at 
                    FROM worker_agent_directory
                """)
                rows = cursor.fetchall()
                
                print(f"Found {len(rows)} worker agents in old table")
                
                for row in rows:
                    agent_name = row[0]
                    user_id = row[1]
                    purpose = row[2]
                    context_json = row[3]
                    created_at = row[4]
                    updated_at = row[5]
                    
                    try:
                        # Parse JSON blob
                        messages = json.loads(context_json) if context_json else []
                        
                        # Check if agent exists in directory_v2
                        cursor.execute("""
                            SELECT 1 FROM worker_agent_directory_v2 
                            WHERE agent_name = ? AND user_id = ?
                        """, (agent_name, user_id))
                        agent_exists = cursor.fetchone()
                        
                        # Get last migrated message if agent exists
                        start_index = 0
                        if agent_exists:
                            cursor.execute("""
                                SELECT message_sequence, role, content
                                FROM worker_agent_context 
                                WHERE agent_name = ? AND user_id = ? 
                                ORDER BY message_sequence DESC 
                                LIMIT 1
                            """, (agent_name, user_id))
                            last_migrated = cursor.fetchone()
                            
                            if last_migrated:
                                last_seq = last_migrated[0]
                                last_role = last_migrated[1]
                                last_content = last_migrated[2]
                                # Verify the last message matches
                                if last_seq <= len(messages):
                                    last_msg = messages[last_seq - 1]
                                    # Compare key fields
                                    if (last_msg.get('role') == last_role and
                                        last_msg.get('content') == last_content):
                                        start_index = last_seq
                                    else:
                                        print(f"  ⚠ Warning: Last message mismatch for {agent_name} ({user_id}), re-migrating")
                                        if not dry_run:
                                            cursor.execute("DELETE FROM worker_agent_context WHERE agent_name = ? AND user_id = ?", (agent_name, user_id))
                                else:
                                    print(f"  ⚠ Warning: More messages in v2 than source for {agent_name} ({user_id}), re-migrating")
                                    if not dry_run:
                                        cursor.execute("DELETE FROM worker_agent_context WHERE agent_name = ? AND user_id = ?", (agent_name, user_id))
                        
                        # Get messages to migrate (only new ones)
                        new_messages = messages[start_index:]
                        
                        if not new_messages and agent_exists:
                            print(f"  ✓ {agent_name} ({user_id}): Already up-to-date ({start_index} messages)")
                            skipped_agents += 1
                            continue
                        
                        # Only print "resuming" message if there are new messages
                        if start_index > 0 and new_messages:
                            print(f"  Resuming {agent_name} ({user_id}): Already migrated {start_index} messages, adding {len(new_messages)} new")
                        
                        if dry_run:
                            msg_info = f"{len(new_messages)} new messages" if agent_exists else f"{len(messages)} messages"
                            print(f"  [DRY RUN] Would migrate {agent_name} ({user_id}) with {msg_info}")
                            migrated_agents += 1
                            migrated_messages += len(new_messages) if agent_exists else len(messages)
                            continue
                        
                        # Insert into directory_v2 if not exists
                        if not agent_exists:
                            cursor.execute("""
                                INSERT INTO worker_agent_directory_v2 
                                (agent_name, user_id, purpose, created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?)
                            """, (agent_name, user_id, purpose, created_at, updated_at))
                        
                        # Insert each new message with sequence
                        for idx, msg in enumerate(new_messages, start=start_index + 1):
                            role = msg.get('role')
                            content = msg.get('content')
                            tool_calls = json.dumps(msg['tool_calls']) if 'tool_calls' in msg else None
                            tool_call_id = msg.get('tool_call_id')
                            tool_name = msg.get('tool_name')
                            
                            cursor.execute("""
                                INSERT INTO worker_agent_context 
                                (agent_name, user_id, message_sequence, role, content, tool_calls, tool_call_id, tool_name)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (agent_name, user_id, idx, role, content, tool_calls, tool_call_id, tool_name))
                        
                        print(f"  ✓ Migrated {agent_name} ({user_id}) with {len(new_messages)} new messages (total: {start_index + len(new_messages)})")
                        migrated_agents += 1
                        migrated_messages += len(new_messages)
                        
                    except Exception as e:
                        print(f"  ✗ Error migrating {agent_name} ({user_id}): {e}")
                        errors += 1
                        continue
                
                if not dry_run:
                    sqlite_conn.commit()
                    print("\n✓ SQLite migration committed")
    
    except Exception as e:
        print(f"\n✗ Fatal error during worker agent migration: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print(f"\nWorker Agent Migration Summary:")
    print(f"  Agents migrated: {migrated_agents}")
    print(f"  Messages migrated: {migrated_messages}")
    print(f"  Agents skipped: {skipped_agents}")
    print(f"  Errors: {errors}")
    
    return errors == 0


def main():
    parser = argparse.ArgumentParser(
        description='Migrate context from JSON blobs to structured v2 tables'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview migration without making changes'
    )
    parser.add_argument(
        '--db-path',
        type=str,
        help='Path to SQLite database (optional, uses default if not provided)'
    )
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print("CONTEXT MIGRATION TO V2 TABLES")
    print("="*70)
    
    if args.dry_run:
        print("\n*** DRY RUN MODE - No changes will be made ***\n")
    
    # Import state module to get shared pool
    from agent.state.state import get_shared_state_pool
    
    # Get database connection
    pool, db_type, sqlite_conn, sqlite_lock, RealDictCursor = get_shared_state_pool()
    
    print(f"Database type: {db_type.upper()}")
    
    if db_type == 'sqlite':
        if args.db_path:
            print(f"Database path: {args.db_path}")
        else:
            print("Using default database path")
    
    # Create v2 tables first
    create_v2_tables(pool, db_type, sqlite_conn, sqlite_lock)
    
    # Run migrations
    print("Starting migration process...")
    
    success = True
    
    # Migrate main agent context
    if not migrate_main_agent_context(pool, db_type, sqlite_conn, sqlite_lock, RealDictCursor, args.dry_run):
        success = False
    
    # Migrate worker agent context
    if not migrate_worker_agent_context(pool, db_type, sqlite_conn, sqlite_lock, RealDictCursor, args.dry_run):
        success = False
    
    # Final summary
    print("\n" + "="*70)
    if args.dry_run:
        print("DRY RUN COMPLETE")
        print("="*70)
        print("\nRun without --dry-run to perform actual migration")
    elif success:
        print("MIGRATION COMPLETE - SUCCESS")
        print("="*70)
        print("\n✓ All data successfully migrated to v2 tables")
        print("✓ Old tables preserved for safety")
        print("\nNext steps:")
        print("  1. Verify data in production")
        print("  2. Monitor application performance")
        print("  3. After 1-2 weeks, consider dropping old tables")
    else:
        print("MIGRATION COMPLETE - WITH ERRORS")
        print("="*70)
        print("\n⚠ Some migrations failed - review errors above")
        print("⚠ Partial migration may have occurred")
        print("\nRecommendation: Fix errors and re-run migration")
    
    print()
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())

