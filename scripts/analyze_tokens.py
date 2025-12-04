#!/usr/bin/env python3
"""
Script to analyze tokens in chats_context for a given user.
Estimates token count and shows bifurcation.
"""

import os
import sys
import json
import sqlite3
from dotenv import load_dotenv
from collections import defaultdict

# Load environment variables
try:
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        load_dotenv()
except Exception as e:
    print(f"Warning: Could not load .env file: {e}")
    # Continue without env file

def estimate_tokens(text):
    """Rough token estimation: 1 token ≈ 4 characters"""
    if not text:
        return 0
    return len(text) / 4

def analyze_sqlite(db_path, user_id):
    """Analyze tokens from SQLite database"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Query all messages for the user
    cursor.execute("""
        SELECT id, message_sequence, role, content, tool_calls, tool_call_id, tool_name
        FROM chats_context
        WHERE user_id = ?
        ORDER BY message_sequence ASC
    """, (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return rows

def analyze_postgres(database_url, user_id):
    """Analyze tokens from PostgreSQL database"""
    import psycopg2
    
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    # Query all messages for the user
    cursor.execute("""
        SELECT id, message_sequence, role, content, tool_calls, tool_call_id, tool_name
        FROM chats_context
        WHERE user_id = %s
        ORDER BY message_sequence ASC
    """, (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return rows

def main():
    # Check if user_id provided
    if len(sys.argv) < 2:
        print("Usage: python analyze_tokens.py <user_id>")
        sys.exit(1)
    
    user_id = sys.argv[1]
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    print(f"\n{'='*80}")
    print(f"Token Analysis for User: {user_id}")
    print(f"{'='*80}\n")
    
    # Fetch data
    if env == 'PROD' and database_url:
        print(f"Using PostgreSQL database...")
        try:
            rows = analyze_postgres(database_url, user_id)
        except Exception as e:
            print(f"Error connecting to PostgreSQL: {e}")
            sys.exit(1)
    else:
        print(f"Using SQLite database...")
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
            'chats.db'
        )
        if not os.path.exists(db_path):
            print(f"Database not found at {db_path}")
            sys.exit(1)
        rows = analyze_sqlite(db_path, user_id)
    
    if not rows:
        print(f"No messages found for user {user_id}")
        sys.exit(0)
    
    # Analyze tokens
    total_tokens = 0
    role_tokens = defaultdict(int)
    role_count = defaultdict(int)
    messages_detail = []
    
    for row in rows:
        row_id, seq, role, content, tool_calls, tool_call_id, tool_name = row
        
        # Calculate tokens for content
        content_tokens = estimate_tokens(content) if content else 0
        
        # Calculate tokens for tool_calls if present
        tool_calls_tokens = 0
        if tool_calls:
            try:
                tool_calls_obj = json.loads(tool_calls) if isinstance(tool_calls, str) else tool_calls
                tool_calls_tokens = estimate_tokens(json.dumps(tool_calls_obj))
            except:
                tool_calls_tokens = estimate_tokens(str(tool_calls))
        
        msg_tokens = content_tokens + tool_calls_tokens
        total_tokens += msg_tokens
        role_tokens[role] += msg_tokens
        role_count[role] += 1
        
        # Store message detail
        content_preview = (content[:100] + "...") if content and len(content) > 100 else content
        messages_detail.append({
            'seq': seq,
            'role': role,
            'tokens': int(msg_tokens),
            'content_length': len(content) if content else 0,
            'preview': content_preview,
            'tool_calls': bool(tool_calls),
            'tool_name': tool_name
        })
    
    # Print summary
    print(f"Total Messages: {len(rows)}")
    print(f"Total Tokens (estimated): {int(total_tokens):,.0f}\n")
    
    print(f"{'Role':<15} {'Count':<10} {'Tokens':<20} {'Avg/Msg':<15}")
    print(f"{'-'*60}")
    for role in sorted(role_tokens.keys()):
        count = role_count[role]
        tokens = role_tokens[role]
        avg = tokens / count if count > 0 else 0
        print(f"{role:<15} {count:<10} {int(tokens):<20,.0f} {int(avg):<15,.0f}")
    
    print(f"{'-'*60}")
    print(f"{'TOTAL':<15} {len(rows):<10} {int(total_tokens):<20,.0f}\n")
    
    # Print top messages by token count
    print(f"\nTop 10 Messages by Token Count:")
    print(f"{'-'*80}")
    print(f"{'#':<5} {'Role':<12} {'Tokens':<12} {'Len':<10} {'Tool':<8} {'Preview':<35}")
    print(f"{'-'*80}")
    
    sorted_msgs = sorted(messages_detail, key=lambda x: x['tokens'], reverse=True)[:10]
    for i, msg in enumerate(sorted_msgs, 1):
        tool_str = "✓" if msg['tool_calls'] else ""
        print(f"{i:<5} {msg['role']:<12} {msg['tokens']:<12,} {msg['content_length']:<10,} {tool_str:<8} {msg['preview'][:35]:<35}")
    
    print(f"\n{'='*80}\n")
    
    # If system prompt is large, warn
    system_msgs = [m for m in messages_detail if m['role'] == 'system']
    if system_msgs:
        sys_tokens = sum(m['tokens'] for m in system_msgs)
        sys_percentage = (sys_tokens / total_tokens * 100) if total_tokens > 0 else 0
        print(f"⚠️  SYSTEM PROMPT TOKENS: {int(sys_tokens):,.0f} ({sys_percentage:.1f}% of total)")
        if sys_percentage > 20:
            print(f"    → System prompt is using {sys_percentage:.1f}% of token budget!")
            print(f"    → Consider reducing system prompt size\n")

if __name__ == "__main__":
    main()

