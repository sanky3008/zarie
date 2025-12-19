"""
MPIM State Helper Module
Provides thread-aware context building for Multi-Party DMs.
"""
import json
import os
from datetime import datetime, timedelta

# Reuse the shared pool from state.py
from agent.state.state import get_shared_state_pool


def _get_connection():
    """Get database connection from shared pool."""
    pool, db_type, conn, lock, RealDictCursor = get_shared_state_pool()
    if db_type == 'postgres':
        return pool.getconn(), db_type, pool, RealDictCursor
    else:
        return conn, db_type, None, None


def _return_connection(conn, db_type, pool):
    """Return connection to pool (only for postgres)."""
    if db_type == 'postgres' and pool:
        pool.putconn(conn)


def get_root_messages(user_id: str, limit: int = 20) -> list:
    """
    Fetch recent root messages (thread_ts IS NULL) for a user/MPIM.
    Returns messages that are not summarised.
    """
    conn, db_type, pool, RealDictCursor = _get_connection()
    
    # SQLite doesn't handle LIMIT NULL well, so use a large number if limit is None
    if limit is None:
        limit = 10000000 
    
    try:
        if db_type == 'postgres':
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT role, content, tool_calls, tool_call_id, tool_name, 
                           created_at, message_sequence, author_id, author_name, slack_ts
                    FROM chats_context 
                    WHERE user_id = %s 
                      AND (is_summarised IS FALSE OR is_summarised IS NULL)
                      AND (thread_ts IS NULL OR thread_ts = '')
                    ORDER BY message_sequence DESC
                    LIMIT %s
                """, (user_id, limit))
                rows = cursor.fetchall()
                # Return in chronological order
                return [dict(row) for row in reversed(rows)]
        else:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT role, content, tool_calls, tool_call_id, tool_name, 
                       created_at, message_sequence, author_id, author_name, slack_ts
                FROM chats_context 
                WHERE user_id = ? 
                  AND (is_summarised = 0 OR is_summarised IS NULL)
                  AND (thread_ts IS NULL OR thread_ts = '')
                ORDER BY message_sequence DESC
                LIMIT ?
            """, (user_id, limit))
            rows = cursor.fetchall()
            columns = ['role', 'content', 'tool_calls', 'tool_call_id', 'tool_name', 
                      'created_at', 'message_sequence', 'author_id', 'author_name', 'slack_ts']
            return [dict(zip(columns, row)) for row in reversed(rows)]
    finally:
        _return_connection(conn, db_type, pool)


def get_thread_messages(user_id: str, thread_ts: str, limit: int = 500) -> list:
    """
    Fetch all messages in a specific thread.
    Includes the parent message (where slack_ts = thread_ts) and all replies.
    """
    conn, db_type, pool, RealDictCursor = _get_connection()
    
    try:
        if db_type == 'postgres':
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT role, content, tool_calls, tool_call_id, tool_name, 
                           created_at, message_sequence, author_id, author_name, slack_ts, thread_ts
                    FROM chats_context 
                    WHERE user_id = %s 
                      AND (slack_ts = %s OR thread_ts = %s)
                    ORDER BY message_sequence ASC
                    LIMIT %s
                """, (user_id, thread_ts, thread_ts, limit))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        else:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT role, content, tool_calls, tool_call_id, tool_name, 
                       created_at, message_sequence, author_id, author_name, slack_ts, thread_ts
                FROM chats_context 
                WHERE user_id = ? 
                  AND (slack_ts = ? OR thread_ts = ?)
                ORDER BY message_sequence ASC
                LIMIT ?
            """, (user_id, thread_ts, thread_ts, limit))
            rows = cursor.fetchall()
            columns = ['role', 'content', 'tool_calls', 'tool_call_id', 'tool_name', 
                      'created_at', 'message_sequence', 'author_id', 'author_name', 'slack_ts', 'thread_ts']
            return [dict(zip(columns, row)) for row in rows]
    finally:
        _return_connection(conn, db_type, pool)


def store_mpim_message(user_id: str, role: str, content: str, 
                       author_id: str = None, author_name: str = None,
                       thread_ts: str = None, slack_ts: str = None,
                       tool_calls: str = None, tool_call_id: str = None, 
                       tool_name: str = None) -> int:
    """
    Store an MPIM message with author and thread metadata.
    Returns the message_sequence number.
    """
    conn, db_type, pool, _ = _get_connection()
    
    try:
        if db_type == 'postgres':
            with conn.cursor() as cursor:
                # Get next sequence number
                cursor.execute(
                    "SELECT COALESCE(MAX(message_sequence), 0) FROM chats_context WHERE user_id = %s",
                    (user_id,)
                )
                max_seq = cursor.fetchone()[0]
                next_seq = max_seq + 1
                
                cursor.execute("""
                    INSERT INTO chats_context 
                    (user_id, message_sequence, role, content, tool_calls, tool_call_id, 
                     tool_name, author_id, author_name, thread_ts, slack_ts)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (user_id, next_seq, role, content, tool_calls, tool_call_id, 
                      tool_name, author_id, author_name, thread_ts, slack_ts))
            conn.commit()
            return next_seq
        else:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COALESCE(MAX(message_sequence), 0) FROM chats_context WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            max_seq = row[0] if row else 0
            next_seq = max_seq + 1
            
            cursor.execute("""
                INSERT INTO chats_context 
                (user_id, message_sequence, role, content, tool_calls, tool_call_id, 
                 tool_name, author_id, author_name, thread_ts, slack_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, next_seq, role, content, tool_calls, tool_call_id, 
                  tool_name, author_id, author_name, thread_ts, slack_ts))
            conn.commit()
            return next_seq
    finally:
        _return_connection(conn, db_type, pool)


def get_cached_slack_user(slack_user_id: str) -> dict:
    """
    Get cached Slack user display name.
    Returns None if not cached or stale (>24 hours).
    """
    conn, db_type, pool, RealDictCursor = _get_connection()
    
    try:
        if db_type == 'postgres':
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT display_name, real_name, updated_at
                    FROM slack_users 
                    WHERE slack_user_id = %s
                """, (slack_user_id,))
                row = cursor.fetchone()
                if row:
                    # Check if stale (>24 hours)
                    updated_at = row['updated_at']
                    if updated_at and (datetime.now() - updated_at) < timedelta(hours=24):
                        return dict(row)
                return None
        else:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT display_name, real_name, updated_at
                FROM slack_users 
                WHERE slack_user_id = ?
            """, (slack_user_id,))
            row = cursor.fetchone()
            if row:
                # For SQLite, updated_at is a string
                updated_at_str = row[2]
                if updated_at_str:
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                        if (datetime.now() - updated_at) < timedelta(hours=24):
                            return {
                                'display_name': row[0],
                                'real_name': row[1],
                                'updated_at': updated_at_str
                            }
                    except:
                        # If parsing fails, return the cached value anyway
                        return {
                            'display_name': row[0],
                            'real_name': row[1],
                            'updated_at': updated_at_str
                        }
            return None
    finally:
        _return_connection(conn, db_type, pool)


def upsert_slack_user(slack_user_id: str, team_id: str, 
                      display_name: str = None, real_name: str = None):
    """
    Insert or update Slack user in cache.
    """
    conn, db_type, pool, _ = _get_connection()
    
    try:
        if db_type == 'postgres':
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO slack_users (slack_user_id, team_id, display_name, real_name, updated_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (slack_user_id) DO UPDATE
                    SET display_name = EXCLUDED.display_name,
                        real_name = EXCLUDED.real_name,
                        updated_at = CURRENT_TIMESTAMP
                """, (slack_user_id, team_id, display_name, real_name))
            conn.commit()
        else:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO slack_users 
                (slack_user_id, team_id, display_name, real_name, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (slack_user_id, team_id, display_name, real_name))
            conn.commit()
    finally:
        _return_connection(conn, db_type, pool)


def format_mpim_messages_for_llm(messages: list, user_timezone: str = 'Asia/Kolkata') -> list:
    """
    Format MPIM messages for LLM context, including author information.
    Returns list of message dicts in LiteLLM format.
    """
    from zoneinfo import ZoneInfo
    
    try:
        tz = ZoneInfo(user_timezone)
    except:
        tz = ZoneInfo('Asia/Kolkata')
    
    formatted = []
    for msg in messages:
        role = msg.get('role')
        content = msg.get('content')
        author_name = msg.get('author_name')
        created_at = msg.get('created_at')
        tool_calls = msg.get('tool_calls')
        tool_call_id = msg.get('tool_call_id')
        tool_name = msg.get('tool_name')
        
        # Format timestamp
        timestamp_str = ""
        if created_at:
            if isinstance(created_at, str):
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                except:
                    dt = datetime.now(tz)
            else:
                dt = created_at
            
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            local_dt = dt.astimezone(tz)
            
            day_name = local_dt.strftime("%A")
            day = local_dt.day
            month = local_dt.strftime("%b")
            year = local_dt.year
            
            if 10 <= day % 100 <= 20:
                suffix = "th"
            else:
                suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
            
            date_str = f"{day_name}, {day}{suffix} {month} {year}"
            time_str = local_dt.strftime("%H:%M")
            timestamp_str = f"Date: {date_str}\nTime: {time_str}\nTimezone: {user_timezone}\n"
        
        if role == 'user':
            # Format with author for MPIM
            if author_name:
                formatted_content = f"{timestamp_str}FROM: End-User via Slack MPIM\nAuthor: {author_name}\nMessage: {content}"
            else:
                formatted_content = f"{timestamp_str}FROM: End-User via Slack MPIM\nMessage: {content}"
            
            formatted.append({
                "role": "user",
                "content": formatted_content
            })
        
        elif role == 'assistant':
            if tool_calls:
                # Parse tool_calls if it's a string
                if isinstance(tool_calls, str):
                    tool_calls = json.loads(tool_calls)
                formatted.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls
                })
            else:
                formatted.append({
                    "role": "assistant",
                    "content": content
                })
        
        elif role == 'tool':
            formatted.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": content
            })
    
    return formatted


def _get_last_n_user_index(messages, n=6):
    """Find the index of the nth last user message."""
    user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if len(user_indices) >= n:
        return user_indices[-n] + 1
    return 0

def _format_background_history(messages):
    """Format messages for background context (System Prompt)."""
    background_lines = []
    for msg in messages:
        role = msg.get('role')
        content = msg.get('content') or ''
        author = msg.get('author_name')
        
        # Smart author labeling
        if role == 'assistant':
            author = "Zarie"
        elif role == 'tool':
            author = "System Info"
            tool_name = msg.get('tool_name') or "Tool"
            content = f"{tool_name} returned: {content}"
        elif not author:
            author = "Unknown User"
            
        # Truncate long messages for background
        if len(content) > 200:
            content = content[:200] + "..."
        background_lines.append(f"[{author}]: {content}")
    
    return "\n".join(background_lines)

async def build_mpim_context(state, user_id: str, thread_ts: str = None, 
                       user_timezone: str = 'Asia/Kolkata',
                       running_summary: str = None) -> dict:
    """
    Build context for MPIM invocation.
    
    Args:
        state: State object for summarisation.
        user_id: The MPIM channel ID.
        thread_ts: The thread ID if this is a thread reply, else None.
        user_timezone: User's timezone.
        running_summary: Current running summary text.
    
    Returns:
        dict with 'system_context' (for system prompt) and 'messages' (for messages array)
    """
    from agent.summarisation import summarise_context
    
    system_context = ""
    messages = []
    
    if thread_ts:
        # --- THREAD CASE ---
        # 1. Fetch Background (Root Messages)
        root_messages = get_root_messages(user_id, limit=50)
        
        # Filter duplication: Exclude thread parent from background
        root_messages = [msg for msg in root_messages if msg.get('slack_ts') != thread_ts]
        
        background_context = _format_background_history(root_messages)
        
        # 2. Fetch Active Context (Thread Messages)
        thread_messages = get_thread_messages(user_id, thread_ts, limit=500)
        messages = format_mpim_messages_for_llm(thread_messages, user_timezone)
        
        is_thread = True
        
    else:
        # --- ROOT CASE (Chat Stream) ---
        # 1. Fetch Full History
        root_messages = get_root_messages(user_id, limit=None)
        
        # 2. Summarisation
        if len(root_messages) > 500:
            # Summarise older messages (keep last 50 for context processing)
            to_summarise = root_messages[:-50]
            # Remaining messages will be processed for splitting
            root_messages = root_messages[-50:]
            
            new_summary = await summarise_context(state, user_id, to_summarise)
            if new_summary:
                running_summary = new_summary
        
        # 3. Split History (Background vs Active) like agent.py
        # We want to put older messages into background to save active tokens
        split_index = _get_last_n_user_index(root_messages, n=6)
        
        background_msgs = root_messages[:split_index]
        active_msgs = root_messages[split_index:]
        
        background_context = _format_background_history(background_msgs)
        messages = format_mpim_messages_for_llm(active_msgs, user_timezone)
        
        is_thread = False

    # Construct Final System Context
    if running_summary:
        system_context += f"\n\n## User Context Summary\n<conversation_summary>\n{running_summary}\n</conversation_summary>"
    
    if background_context:
        system_context += f"\n\n## Recent Channel Activity (Background)\n<conversation_history>\n{background_context}\n</conversation_history>"
    
    return {
        'system_context': system_context,
        'messages': messages,
        'is_thread': is_thread
    }
