import sqlite3
import json
import threading
import os

class _DummyLock:
    """A lock that doesn't do anything."""
    def __enter__(self):
        pass
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

# Module-level shared pool for State (used by prompt.py)
_shared_state_pool = None
_shared_state_db_type = None
_shared_state_sqlite_conn = None
_shared_state_sqlite_lock = None
_shared_state_realdict_cursor = None

def get_shared_state_pool():
    """Get or create the shared connection pool for State (used by prompt.py)"""
    global _shared_state_pool, _shared_state_db_type, _shared_state_sqlite_conn, _shared_state_sqlite_lock, _shared_state_realdict_cursor
    
    if _shared_state_pool is not None or _shared_state_sqlite_conn is not None:
        return _shared_state_pool, _shared_state_db_type, _shared_state_sqlite_conn, _shared_state_sqlite_lock, _shared_state_realdict_cursor
    
    # Check environment to determine which database to use
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    # Force PROD to use PostgreSQL, LOCAL to use SQLite
    use_postgres = (env == 'PROD' and database_url is not None)
    
    if use_postgres:
        # Use PostgreSQL with connection pool (only if ENV=PROD and DATABASE_URL exists)
        import psycopg2.pool
        from psycopg2.extras import RealDictCursor
        
        _shared_state_db_type = 'postgres'
        _shared_state_pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=database_url)
        _shared_state_realdict_cursor = RealDictCursor
        _shared_state_sqlite_lock = None
    else:
        # Use SQLite for local development (default unless ENV=PROD)
        _shared_state_db_type = 'sqlite'
        # Go up 4 levels from state.py -> state/ -> agent/ -> alpha-v0.1/ -> chats.db
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'chats.db')
        _shared_state_sqlite_conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        _shared_state_sqlite_conn.execute("PRAGMA journal_mode=WAL")
        _shared_state_sqlite_conn.execute("PRAGMA busy_timeout=30000")
        _shared_state_sqlite_lock = threading.Lock()
        _shared_state_realdict_cursor = None
    
    return _shared_state_pool, _shared_state_db_type, _shared_state_sqlite_conn, _shared_state_sqlite_lock, _shared_state_realdict_cursor

class State:
    def __init__(self, db_path=None):
        """Initialize the State class and connect to the database."""
        # Default to parent directory for local development
        if db_path is None:
            # Go up 4 levels from state.py -> state/ -> agent/ -> alpha-v0.1/ -> chats.db
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'chats.db')
        self.db_path = db_path
        self.lock = _DummyLock() # Start with a dummy lock
        
        # Use shared pool instead of creating new pool
        # The pool respects ENV variable (PROD=postgres, LOCAL=sqlite)
        self.pool, self.db_type, self.conn, self.lock, self.RealDictCursor = get_shared_state_pool()
        
        if self.db_type == 'postgres':
            # PostgreSQL uses pool, RealDictCursor already set
            pass
        else:
            # SQLite - use shared connection and lock
            self.cursor = self.conn.cursor()
        
        # Create the table
        self._initialize_database()
    
    def __del__(self):
        """Close the database connection when the object is destroyed."""
        # Don't close shared pool here - it's shared across instances
        # The pool will be closed when the module is unloaded
        pass
    
    def _initialize_database(self):
        """Create the chats table and chats_context table if they don't exist."""
        if self.db_type == 'postgres':
            # Get a temporary connection from the pool to initialize the DB
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    # Keep old table for backward compatibility
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS chats (
                            user_id TEXT PRIMARY KEY,
                            context TEXT NOT NULL
                        )
                    """)
                    
                    # Create new structured context table
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS chats_context (
                            id SERIAL PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            message_sequence INTEGER NOT NULL,
                            role TEXT NOT NULL,
                            content TEXT,
                            tool_calls TEXT,
                            tool_call_id TEXT,
                            tool_name TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id, message_sequence)
                        )
                    """)
                    
                    # Create index for efficient querying
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_chats_context_user_seq 
                        ON chats_context(user_id, message_sequence)
                    """)
                    
                    # MPIM support columns (idempotent)
                    cursor.execute("ALTER TABLE chats_context ADD COLUMN IF NOT EXISTS author_id TEXT")
                    cursor.execute("ALTER TABLE chats_context ADD COLUMN IF NOT EXISTS author_name TEXT")
                    cursor.execute("ALTER TABLE chats_context ADD COLUMN IF NOT EXISTS thread_ts TEXT")
                    cursor.execute("ALTER TABLE chats_context ADD COLUMN IF NOT EXISTS slack_ts TEXT")
                    cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS user_type TEXT DEFAULT 'user'")
                    cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS has_welcomed BOOLEAN DEFAULT FALSE")
                    
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_chats_context_thread 
                        ON chats_context(user_id, thread_ts)
                    """)
                    
                    # Slack users cache table
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS slack_users (
                            slack_user_id TEXT PRIMARY KEY,
                            team_id TEXT NOT NULL,
                            display_name TEXT,
                            display_name TEXT,
                            real_name TEXT,
                            timezone TEXT,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_slack_users_team 
                        ON slack_users(team_id)
                    """)
                    
                    # Add timezone column if not exists (Postgres)
                    cursor.execute("ALTER TABLE slack_users ADD COLUMN IF NOT EXISTS timezone TEXT")
                    
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:  # sqlite
            with self.lock:
                # Keep old table for backward compatibility
                self.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chats (
                        user_id TEXT PRIMARY KEY,
                        context TEXT NOT NULL
                    )
                """)
                
                # Create new structured context table
                self.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chats_context (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        message_sequence INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT,
                        tool_calls TEXT,
                        tool_call_id TEXT,
                        tool_name TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id, message_sequence)
                    )
                """)
                
                # Create index for efficient querying
                self.cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chats_context_user_seq 
                    ON chats_context(user_id, message_sequence)
                """)
                
                # MPIM support columns (check and add if not exists)
                self.cursor.execute("PRAGMA table_info(chats_context)")
                existing_cols = [col[1] for col in self.cursor.fetchall()]
                
                if 'author_id' not in existing_cols:
                    self.cursor.execute("ALTER TABLE chats_context ADD COLUMN author_id TEXT")
                if 'author_name' not in existing_cols:
                    self.cursor.execute("ALTER TABLE chats_context ADD COLUMN author_name TEXT")
                if 'thread_ts' not in existing_cols:
                    self.cursor.execute("ALTER TABLE chats_context ADD COLUMN thread_ts TEXT")
                if 'slack_ts' not in existing_cols:
                    self.cursor.execute("ALTER TABLE chats_context ADD COLUMN slack_ts TEXT")
                
                # Check users table for user_type column
                self.cursor.execute("PRAGMA table_info(users)")
                user_cols = [col[1] for col in self.cursor.fetchall()]
                if 'user_type' not in user_cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN user_type TEXT DEFAULT 'user'")
                if 'has_welcomed' not in user_cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN has_welcomed INTEGER DEFAULT 0")
                
                self.cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chats_context_thread 
                    ON chats_context(user_id, thread_ts)
                """)
                
                # Slack users cache table
                self.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS slack_users (
                        slack_user_id TEXT PRIMARY KEY,
                        team_id TEXT NOT NULL,
                        display_name TEXT,
                        real_name TEXT,
                        timezone TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                self.cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_slack_users_team 
                    ON slack_users(team_id)
                """)
                
                # Check slack_users table for timezone column
                self.cursor.execute("PRAGMA table_info(slack_users)")
                slack_user_cols = [col[1] for col in self.cursor.fetchall()]
                if 'timezone' not in slack_user_cols:
                    self.cursor.execute("ALTER TABLE slack_users ADD COLUMN timezone TEXT")
                
                self.conn.commit()
    
    def get_context(self, user_id):
        """Get the context list for a given user_id from chats_context table."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    # Also fetch message_sequence to help with summarization cutoff
                    cursor.execute("""
                        SELECT role, content, tool_calls, tool_call_id, tool_name, created_at, message_sequence
                        FROM chats_context 
                        WHERE user_id = %s AND (is_summarised IS FALSE OR is_summarised IS NULL)
                        ORDER BY message_sequence ASC
                    """, (user_id,))
                    rows = cursor.fetchall()
                    
                    # Reconstruct messages list
                    messages = []
                    for row in rows:
                        content = row['content']
                        tool_name = row['tool_name']
                        
                        # Truncate content for Brave Search tools
                        if tool_name in ['brave_web_search', 'brave_local_search', 'brave_news_search', 'brave_image_search', 'brave_video_search']:
                            if content and len(content) > 200:
                                content = content[:200] + "...[TRUNCATED]"
                        
                        msg = {
                            "role": row['role'],
                            "content": content,
                            "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                            "message_sequence": row['message_sequence']
                        }
                        # Add tool_calls if present
                        if row['tool_calls']:
                            msg['tool_calls'] = json.loads(row['tool_calls'])
                        # Add tool metadata for tool responses
                        if row['tool_call_id']:
                            msg['tool_call_id'] = row['tool_call_id']
                        if tool_name:
                            msg['tool_name'] = tool_name
                        messages.append(msg)
                    
                    return json.dumps(messages) if messages else None
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                # Also fetch message_sequence
                self.cursor.execute("""
                    SELECT role, content, tool_calls, tool_call_id, tool_name, created_at, message_sequence
                    FROM chats_context 
                    WHERE user_id = ? AND (is_summarised = 0 OR is_summarised IS NULL)
                    ORDER BY message_sequence ASC
                """, (user_id,))
                rows = self.cursor.fetchall()
                
                # Reconstruct messages list
                messages = []
                for row in rows:
                    content = row[1]
                    tool_name = row[4]
                    
                    # Truncate content for Brave Search tools
                    if tool_name in ['brave_web_search', 'brave_local_search', 'brave_news_search', 'brave_image_search', 'brave_video_search']:
                        if content and len(content) > 200:
                            content = content[:200] + "...[TRUNCATED]"
                    
                    msg = {
                        "role": row[0],
                        "content": content,
                        "created_at": row[5],
                        "message_sequence": row[6]
                    }
                    # Add tool_calls if present
                    if row[2]:
                        msg['tool_calls'] = json.loads(row[2])
                    # Add tool metadata for tool responses
                    if row[3]:
                        msg['tool_call_id'] = row[3]
                    if tool_name:
                        msg['tool_name'] = tool_name
                    messages.append(msg)
                
                return json.dumps(messages) if messages else None
    
    def add_context(self, user_id, response_or_responses, thread_ts=None, slack_ts=None, author_id=None, author_name=None):
        """Add context for a given user_id to chats_context table. Can handle single response or list of responses."""
        if isinstance(response_or_responses, list):
            responses = response_or_responses
        else:
            responses = [response_or_responses]
        
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    # Get current max sequence number
                    cursor.execute(
                        "SELECT COALESCE(MAX(message_sequence), 0) FROM chats_context WHERE user_id = %s",
                        (user_id,)
                    )
                    max_seq = cursor.fetchone()[0]
                    
                    # Insert each message with incremented sequence
                    for i, response in enumerate(responses):
                        seq = max_seq + i + 1
                        role = response.get('role')
                        content = response.get('content')
                        tool_calls = None
                        tool_call_id = None
                        tool_name = None
                        
                        # Extract tool_calls if present
                        if 'tool_calls' in response:
                            tool_calls = json.dumps(response['tool_calls'])
                        
                        # Extract tool metadata if present
                        if 'tool_call_id' in response:
                            tool_call_id = response['tool_call_id']
                        if 'name' in response:
                            tool_name = response['name']
                        
                        cursor.execute("""
                            INSERT INTO chats_context 
                            (user_id, message_sequence, role, content, tool_calls, tool_call_id, 
                             tool_name, thread_ts, slack_ts, author_id, author_name)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (user_id, seq, role, content, tool_calls, tool_call_id, tool_name, 
                              thread_ts, slack_ts, author_id, author_name))
                
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                # Get the current max sequence number
                self.cursor.execute(
                    "SELECT COALESCE(MAX(message_sequence), 0) FROM chats_context WHERE user_id = ?",
                    (user_id,)
                )
                row = self.cursor.fetchone()
                max_seq = row[0] if row else 0
                
                # Insert each message with incremented sequence
                for i, response in enumerate(responses):
                    seq = max_seq + i + 1
                    role = response.get('role')
                    content = response.get('content')
                    tool_calls = None
                    tool_call_id = None
                    tool_name = None
                    
                    # Extract tool_calls if present
                    if 'tool_calls' in response:
                        tool_calls = json.dumps(response['tool_calls'])
                    
                    # Extract tool metadata if present
                    if 'tool_call_id' in response:
                        tool_call_id = response['tool_call_id']
                    if 'name' in response:
                        tool_name = response['name']
                    
                    self.cursor.execute("""
                        INSERT INTO chats_context 
                        (user_id, message_sequence, role, content, tool_calls, tool_call_id, 
                         tool_name, thread_ts, slack_ts, author_id, author_name)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (user_id, seq, role, content, tool_calls, tool_call_id, tool_name, 
                          thread_ts, slack_ts, author_id, author_name))
                
                self.conn.commit()

    def get_context(self, user_id):
        """Legacy wrapper for get_messages to maintain backward compatibility."""
        messages = self.get_messages(user_id, exclude_summarised=True)
        return json.dumps(messages) if messages else None

    def get_messages(self, user_id, thread_ts=None, limit=None, exclude_summarised=False):
        """
        Flexible message retrieval for both DMs and MPIMs/Threads.
        
        Args:
            user_id: The ID of the user or channel.
            thread_ts: If set, fetches messages for a specific thread (including the root parent).
            limit: Max number of messages to return.
            exclude_summarised: If True, only returns unsummarised messages.
        """
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    query = """
                        SELECT role, content, tool_calls, tool_call_id, tool_name, 
                               created_at, message_sequence, author_id, author_name, slack_ts, thread_ts
                        FROM chats_context 
                        WHERE user_id = %s
                    """
                    params = [user_id]
                    
                    if exclude_summarised:
                        query += " AND (is_summarised IS FALSE OR is_summarised IS NULL)"
                    
                    if thread_ts:
                        # Fetch thread replies + the root message (slack_ts = thread_ts)
                        query += " AND (thread_ts = %s OR slack_ts = %s)"
                        params.extend([thread_ts, thread_ts])
                    else:
                        # Fetch unrelated to threads OR root messages of threads?
                        # Standard get_context behavior usually just fetches everything chronological
                        # But for MPIM "Root Context" we specifically want thread_ts IS NULL
                        # Let's keep it flexible: if thread_ts is explicitly None, maybe we don't filter?
                        # Actually, to replicate get_root_messages behavior, we might need another flag.
                        # But for standard Agent behavior (non-threaded), we usually ignore thread_ts column.
                        pass

                    query += " ORDER BY message_sequence ASC"
                    
                    if limit:
                        query += " LIMIT %s"
                        params.append(limit)
                        
                    cursor.execute(query, tuple(params))
                    rows = cursor.fetchall()
                    
                    return self._process_rows(rows)
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                query = """
                    SELECT role, content, tool_calls, tool_call_id, tool_name, 
                           created_at, message_sequence, author_id, author_name, slack_ts, thread_ts
                    FROM chats_context 
                    WHERE user_id = ?
                """
                params = [user_id]
                
                if exclude_summarised:
                    query += " AND (is_summarised = 0 OR is_summarised IS NULL)"
                
                if thread_ts:
                    query += " AND (thread_ts = ? OR slack_ts = ?)"
                    params.extend([thread_ts, thread_ts])
                
                query += " ORDER BY message_sequence ASC"
                
                if limit:
                    query += " LIMIT ?"
                    params.append(limit)
                
                self.cursor.execute(query, tuple(params))
                rows = self.cursor.fetchall()
                
                # Convert tuple rows to dicts
                columns = ['role', 'content', 'tool_calls', 'tool_call_id', 'tool_name', 
                          'created_at', 'message_sequence', 'author_id', 'author_name', 'slack_ts', 'thread_ts']
                dict_rows = [dict(zip(columns, row)) for row in rows]
                
                return self._process_rows(dict_rows)

    def _process_rows(self, rows):
        """Helper to process DB rows into message dicts."""
        messages = []
        for row in rows:
            content = row['content']
            tool_name = row['tool_name']
            
            # Truncate content for Brave Search tools
            if tool_name in ['brave_web_search', 'brave_local_search', 'brave_news_search', 'brave_image_search', 'brave_video_search']:
                if content and len(content) > 200:
                    content = content[:200] + "...[TRUNCATED]"
            
            msg = {
                "role": row['role'],
                "content": content,
                "created_at": row['created_at'].isoformat() if hasattr(row.get('created_at'), 'isoformat') else row.get('created_at'),
                "message_sequence": row['message_sequence'],
                "author_id": row.get('author_id'),
                "author_name": row.get('author_name'),
                "thread_ts": row.get('thread_ts'),
                "slack_ts": row.get('slack_ts')
            }
            # Add tool_calls if present
            if row['tool_calls']:
                try:
                    msg['tool_calls'] = json.loads(row['tool_calls'])
                except:
                    pass
            # Add tool metadata for tool responses
            if row['tool_call_id']:
                msg['tool_call_id'] = row['tool_call_id']
            if tool_name:
                msg['tool_name'] = tool_name
            messages.append(msg)
        return messages

    # --- Slack User Cache Methods (Moved from mpim_state) ---
    def get_cached_slack_user(self, slack_user_id):
        """Get cached Slack user display name."""
        from datetime import datetime, timedelta
        
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    cursor.execute("""
                        SELECT display_name, real_name, timezone, updated_at
                        FROM slack_users 
                        WHERE slack_user_id = %s
                    """, (slack_user_id,))
                    row = cursor.fetchone()
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("""
                    SELECT display_name, real_name, timezone, updated_at
                    FROM slack_users 
                    WHERE slack_user_id = ?
                """, (slack_user_id,))
                tuple_row = self.cursor.fetchone()
                row = {'display_name': tuple_row[0], 'real_name': tuple_row[1], 'timezone': tuple_row[2], 'updated_at': tuple_row[3]} if tuple_row else None

        if row:
            updated_at = row['updated_at']
            # Normalize timestamp
            if isinstance(updated_at, str):
                try:
                    updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                except:
                    pass 
            
            # Check staleness
            if isinstance(updated_at, datetime) and (datetime.now(updated_at.tzinfo) - updated_at) < timedelta(hours=24):
                return row
            elif not isinstance(updated_at, datetime):
                 # Fallback if parsing failed but data exists
                 return row
                 
        return None

    def upsert_slack_user(self, slack_user_id, team_id, display_name=None, real_name=None, timezone=None):
        """Insert or update Slack user in cache."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO slack_users (slack_user_id, team_id, display_name, real_name, timezone, updated_at)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (slack_user_id) DO UPDATE
                        SET display_name = EXCLUDED.display_name,
                            real_name = EXCLUDED.real_name,
                            timezone = EXCLUDED.timezone,
                            updated_at = CURRENT_TIMESTAMP
                    """, (slack_user_id, team_id, display_name, real_name, timezone))
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("""
                    INSERT OR REPLACE INTO slack_users 
                    (slack_user_id, team_id, display_name, real_name, timezone, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (slack_user_id, team_id, display_name, real_name, timezone))
                self.conn.commit()

    def get_running_summary(self, user_id):
        """Get the running summary for a user."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT running_summary FROM users WHERE telegram_id = %s", (user_id,))
                    row = cursor.fetchone()
                    return row[0] if row else None
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("SELECT running_summary FROM users WHERE telegram_id = ?", (user_id,))
                row = self.cursor.fetchone()
                return row[0] if row else None

    def update_running_summary(self, user_id, summary):
        """Update the running summary for a user."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE users SET running_summary = %s WHERE telegram_id = %s", (summary, user_id))
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("UPDATE users SET running_summary = ? WHERE telegram_id = ?", (summary, user_id))
                self.conn.commit()

    def mark_messages_up_to_sequence(self, user_id, max_sequence):
        """Mark all messages up to (and including) max_sequence as summarised."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE chats_context 
                        SET is_summarised = TRUE 
                        WHERE user_id = %s AND message_sequence <= %s
                    """, (user_id, max_sequence))
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("""
                    UPDATE chats_context 
                    SET is_summarised = 1 
                    WHERE user_id = ? AND message_sequence <= ?
                """, (user_id, max_sequence))
                self.conn.commit()


