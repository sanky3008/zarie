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
                self.conn.commit()
    
    def get_context(self, user_id):
        """Get the context list for a given user_id from chats_context table."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    cursor.execute("""
                        SELECT role, content, tool_calls, tool_call_id, tool_name 
                        FROM chats_context 
                        WHERE user_id = %s 
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
                            if content and len(content) > 2000:
                                content = content[:2000] + "...[TRUNCATED]"
                        
                        msg = {
                            "role": row['role'],
                            "content": content
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
                self.cursor.execute("""
                    SELECT role, content, tool_calls, tool_call_id, tool_name 
                    FROM chats_context 
                    WHERE user_id = ? 
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
                        if content and len(content) > 2000:
                            content = content[:2000] + "...[TRUNCATED]"
                    
                    msg = {
                        "role": row[0],
                        "content": content
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
    
    def add_context(self, user_id, response_or_responses):
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
                            (user_id, message_sequence, role, content, tool_calls, tool_call_id, tool_name)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (user_id, seq, role, content, tool_calls, tool_call_id, tool_name))
                
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
                        (user_id, message_sequence, role, content, tool_calls, tool_call_id, tool_name)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (user_id, seq, role, content, tool_calls, tool_call_id, tool_name))
                
                self.conn.commit()

