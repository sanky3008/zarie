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
    
    database_url = os.getenv('DATABASE_URL')
    
    if database_url:
        # Use PostgreSQL with connection pool
        import psycopg2.pool
        from psycopg2.extras import RealDictCursor
        
        _shared_state_db_type = 'postgres'
        _shared_state_pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=database_url)
        _shared_state_realdict_cursor = RealDictCursor
        _shared_state_sqlite_lock = None
    else:
        # Use SQLite for local development
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
        
        # Check if DATABASE_URL exists (Railway PostgreSQL)
        database_url = os.getenv('DATABASE_URL')
        
        # Use shared pool instead of creating new pool
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
        """Create the chats table if it doesn't exist."""
        if self.db_type == 'postgres':
            # Get a temporary connection from the pool to initialize the DB
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS chats (
                            user_id TEXT PRIMARY KEY,
                            context TEXT NOT NULL
                        )
                    """)
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:  # sqlite
            with self.lock:
                self.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chats (
                        user_id TEXT PRIMARY KEY,
                        context TEXT NOT NULL
                    )
                """)
                self.conn.commit()
    
    def get_context(self, user_id):
        """Get the context BLOB for a given user_id."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    cursor.execute("SELECT context FROM chats WHERE user_id = %s", (user_id,))
                    row = cursor.fetchone()
                    return row['context'] if row else None
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("SELECT context FROM chats WHERE user_id = ?", (user_id,))
                row = self.cursor.fetchone()
                return row[0] if row else None
    
    def add_context(self, user_id, response_or_responses):
        """Add context for a given user_id. Can handle single response or list of responses."""
        if isinstance(response_or_responses, list):
            responses = response_or_responses
        else:
            responses = [response_or_responses]
        
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    # Get current context
                    cursor.execute("SELECT context FROM chats WHERE user_id = %s", (user_id,))
                    row = cursor.fetchone()
                    context_blob = row['context'] if row else None
                    
                    # Modify context
                    context = json.loads(context_blob) if context_blob else []
                    context.extend(responses)
                    context_json = json.dumps(context)
                    
                    # Write back to DB
                    cursor.execute("""
                        INSERT INTO chats (user_id, context) VALUES (%s, %s)
                        ON CONFLICT (user_id) DO UPDATE SET context = EXCLUDED.context
                    """, (user_id, context_json))
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                # Get the current context
                self.cursor.execute("SELECT context FROM chats WHERE user_id = ?", (user_id,))
                row = self.cursor.fetchone()
                context_blob = row[0] if row else None
                
                # Parse the existing context or create new list
                if context_blob:
                    context = json.loads(context_blob)
                else:
                    context = []
                
                # Append all responses to the context atomically
                context.extend(responses)
                
                # Save the updated context back to the database
                context_json = json.dumps(context)
                
                # SQLite INSERT OR REPLACE
                if context_blob:
                    self.cursor.execute(
                        "UPDATE chats SET context = ? WHERE user_id = ?",
                        (context_json, user_id)
                    )
                else:
                    self.cursor.execute(
                        "INSERT INTO chats (user_id, context) VALUES (?, ?)",
                        (context_json, user_id)
                    )
                
                self.conn.commit()

