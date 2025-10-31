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

# Module-level pool shared with tools.py
_shared_pool = None
_shared_db_type = None
_shared_sqlite_conn = None
_shared_sqlite_lock = None
_shared_realdict_cursor = None

def get_shared_pool():
    """Get or create the shared connection pool for worker agent"""
    global _shared_pool, _shared_db_type, _shared_sqlite_conn, _shared_sqlite_lock, _shared_realdict_cursor
    
    if _shared_pool is not None or _shared_sqlite_conn is not None:
        return _shared_pool, _shared_db_type, _shared_sqlite_conn, _shared_sqlite_lock, _shared_realdict_cursor
    
    database_url = os.getenv('DATABASE_URL')
    
    if database_url:
        # Use PostgreSQL with connection pool
        import psycopg2.pool
        from psycopg2.extras import RealDictCursor
        
        _shared_db_type = 'postgres'
        _shared_pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=database_url)
        _shared_realdict_cursor = RealDictCursor
        _shared_sqlite_lock = None
    else:
        # Use SQLite for local development
        _shared_db_type = 'sqlite'
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'chats.db')
        _shared_sqlite_conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        _shared_sqlite_conn.execute("PRAGMA journal_mode=WAL")
        _shared_sqlite_conn.execute("PRAGMA busy_timeout=30000")
        _shared_sqlite_lock = threading.Lock()
    
    return _shared_pool, _shared_db_type, _shared_sqlite_conn, _shared_sqlite_lock, _shared_realdict_cursor

class Directory:
    def __init__(self, db_path=None):
        """Initialize the Directory class and connect to the database."""
        # Use the shared pool
        self.pool, self.db_type, self.conn, self.lock, self.RealDictCursor = get_shared_pool()
        
        # Set up cursor based on database type
        if self.db_type == 'sqlite':
            self.cursor = self.conn.cursor()
        else:
            # PostgreSQL doesn't need a cursor here
            pass
        
        # Table already created by migration script
    
    def get_agent(self, agent_name, user_id):
        """Get the agent record for a given agent_name and user_id."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    cursor.execute("""
                        SELECT agent_name, user_id, purpose, context, created_at, updated_at 
                        FROM worker_agent_directory 
                        WHERE agent_name = %s AND user_id = %s
                    """, (agent_name, user_id))
                    row = cursor.fetchone()
                    return row if row else None
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("""
                    SELECT agent_name, user_id, purpose, context, created_at, updated_at 
                    FROM worker_agent_directory 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
                row = self.cursor.fetchone()
                if row:
                    return {
                        'agent_name': row[0],
                        'user_id': row[1],
                        'purpose': row[2],
                        'context': row[3],
                        'created_at': row[4],
                        'updated_at': row[5]
                    }
                return None
    
    def get_context(self, agent_name, user_id):
        """Get the context for a given agent_name and user_id."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    cursor.execute("""
                        SELECT context FROM worker_agent_directory 
                        WHERE agent_name = %s AND user_id = %s
                    """, (agent_name, user_id))
                    row = cursor.fetchone()
                    return row['context'] if row else None
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("""
                    SELECT context FROM worker_agent_directory 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
                row = self.cursor.fetchone()
                return row[0] if row else None
    
    def add_context(self, agent_name, user_id, response_or_responses, purpose=None):
        """Add context for a given agent. Can handle single response or list of responses."""
        # Normalize input to always be a list
        if isinstance(response_or_responses, list):
            responses = response_or_responses
        else:
            responses = [response_or_responses]
        
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    # Get current context
                    cursor.execute("""
                        SELECT context FROM worker_agent_directory 
                        WHERE agent_name = %s AND user_id = %s
                    """, (agent_name, user_id))
                    row = cursor.fetchone()
                    context_blob = row['context'] if row else None
                    
                    # Modify context
                    context = json.loads(context_blob) if context_blob else []
                    context.extend(responses)
                    context_json = json.dumps(context)
                    
                    # Write back to DB
                    cursor.execute("""
                        INSERT INTO worker_agent_directory (agent_name, user_id, purpose, context, updated_at) 
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (agent_name, user_id) 
                        DO UPDATE SET 
                            context = EXCLUDED.context,
                            updated_at = CURRENT_TIMESTAMP
                    """, (agent_name, user_id, purpose, context_json))
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                # Get the current context
                self.cursor.execute("""
                    SELECT context FROM worker_agent_directory 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
                row = self.cursor.fetchone()
                context_blob = row[0] if row else None
                
                # Parse the existing context or create new list
                context = json.loads(context_blob) if context_blob else []
                
                # Append all responses to the context atomically
                context.extend(responses)
                
                # Save the updated context back to the database
                context_json = json.dumps(context)
                
                # SQLite INSERT OR REPLACE
                if context_blob:
                    self.cursor.execute("""
                        UPDATE worker_agent_directory 
                        SET context = ?, updated_at = CURRENT_TIMESTAMP 
                        WHERE agent_name = ? AND user_id = ?
                    """, (context_json, agent_name, user_id))
                else:
                    self.cursor.execute("""
                        INSERT INTO worker_agent_directory (agent_name, user_id, purpose, context) 
                        VALUES (?, ?, ?, ?)
                    """, (agent_name, user_id, purpose, context_json))
                
                self.conn.commit()
    
    def create_agent(self, agent_name, user_id, purpose, initial_context=None):
        """Create a new worker agent with optional initial context."""
        # Prepare initial context
        if initial_context is None:
            context = []
        elif isinstance(initial_context, list):
            context = initial_context
        else:
            context = [initial_context]
        
        context_json = json.dumps(context)
        
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO worker_agent_directory (agent_name, user_id, purpose, context)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (agent_name, user_id) 
                        DO UPDATE SET 
                            purpose = EXCLUDED.purpose,
                            context = EXCLUDED.context,
                            updated_at = CURRENT_TIMESTAMP
                    """, (agent_name, user_id, purpose, context_json))
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("""
                    INSERT OR REPLACE INTO worker_agent_directory (agent_name, user_id, purpose, context)
                    VALUES (?, ?, ?, ?)
                """, (agent_name, user_id, purpose, context_json))
                self.conn.commit()
    
    def delete_agent(self, agent_name, user_id):
        """Delete a worker agent."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        DELETE FROM worker_agent_directory 
                        WHERE agent_name = %s AND user_id = %s
                    """, (agent_name, user_id))
                    rowcount = cursor.rowcount
                conn.commit()
                return rowcount > 0
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("""
                    DELETE FROM worker_agent_directory 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
                rowcount = self.cursor.rowcount
                self.conn.commit()
                return rowcount > 0
    
    def list_agents(self, user_id):
        """List all agents for a given user."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    cursor.execute("""
                        SELECT agent_name, purpose, created_at, updated_at 
                        FROM worker_agent_directory 
                        WHERE user_id = %s
                        ORDER BY updated_at DESC
                    """, (user_id,))
                    return cursor.fetchall()
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("""
                    SELECT agent_name, purpose, created_at, updated_at 
                    FROM worker_agent_directory 
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                """, (user_id,))
                rows = self.cursor.fetchall()
                return [
                    {
                        'agent_name': row[0],
                        'purpose': row[1],
                        'created_at': row[2],
                        'updated_at': row[3]
                    }
                    for row in rows
                ]

