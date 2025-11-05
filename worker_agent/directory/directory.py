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
        
        # Create tables
        self._initialize_database()
    
    def _initialize_database(self):
        """Create the worker agent tables if they don't exist."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    # Keep old table for backward compatibility
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS worker_agent_directory (
                            agent_name TEXT NOT NULL,
                            user_id TEXT NOT NULL,
                            purpose TEXT,
                            context TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (agent_name, user_id)
                        )
                    """)
                    
                    # Create new metadata table
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
                    
                    # Create new context table
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS worker_agent_context (
                            id SERIAL PRIMARY KEY,
                            agent_name TEXT NOT NULL,
                            user_id TEXT NOT NULL,
                            message_sequence INTEGER NOT NULL,
                            role TEXT NOT NULL,
                            content TEXT,
                            tool_calls TEXT,
                            tool_call_id TEXT,
                            tool_name TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(agent_name, user_id, message_sequence),
                            FOREIGN KEY (agent_name, user_id) REFERENCES worker_agent_directory_v2(agent_name, user_id)
                        )
                    """)
                    
                    # Create index for efficient querying
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_worker_context_agent_user_seq 
                        ON worker_agent_context(agent_name, user_id, message_sequence)
                    """)
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:  # sqlite
            with self.lock:
                # Keep old table for backward compatibility
                self.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS worker_agent_directory (
                        agent_name TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        purpose TEXT,
                        context TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (agent_name, user_id)
                    )
                """)
                
                # Create new metadata table
                self.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS worker_agent_directory_v2 (
                        agent_name TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        purpose TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (agent_name, user_id)
                    )
                """)
                
                # Note: SQLite doesn't support ALTER COLUMN DROP NOT NULL directly
                # Purpose column should be nullable in this schema
                
                # Create new context table
                self.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS worker_agent_context (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agent_name TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        message_sequence INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT,
                        tool_calls TEXT,
                        tool_call_id TEXT,
                        tool_name TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(agent_name, user_id, message_sequence)
                    )
                """)
                
                # Create index for efficient querying
                self.cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_worker_context_agent_user_seq 
                    ON worker_agent_context(agent_name, user_id, message_sequence)
                """)
                self.conn.commit()
    
    def get_agent(self, agent_name, user_id):
        """Get the agent record for a given agent_name and user_id from v2 table."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    cursor.execute("""
                        SELECT agent_name, user_id, purpose, created_at, updated_at 
                        FROM worker_agent_directory_v2 
                        WHERE agent_name = %s AND user_id = %s
                    """, (agent_name, user_id))
                    row = cursor.fetchone()
                    return row if row else None
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("""
                    SELECT agent_name, user_id, purpose, created_at, updated_at 
                    FROM worker_agent_directory_v2 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
                row = self.cursor.fetchone()
                if row:
                    return {
                        'agent_name': row[0],
                        'user_id': row[1],
                        'purpose': row[2],
                        'created_at': row[3],
                        'updated_at': row[4]
                    }
                return None
    
    def get_context(self, agent_name, user_id):
        """Get the context list for a given agent_name and user_id from context table."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    cursor.execute("""
                        SELECT role, content, tool_calls, tool_call_id, tool_name 
                        FROM worker_agent_context 
                        WHERE agent_name = %s AND user_id = %s 
                        ORDER BY message_sequence ASC
                    """, (agent_name, user_id))
                    rows = cursor.fetchall()
                    
                    # Reconstruct messages list
                    messages = []
                    for row in rows:
                        msg = {
                            "role": row['role'],
                            "content": row['content']
                        }
                        # Add tool_calls if present
                        if row['tool_calls']:
                            msg['tool_calls'] = json.loads(row['tool_calls'])
                        # Add tool metadata for tool responses
                        if row['tool_call_id']:
                            msg['tool_call_id'] = row['tool_call_id']
                        if row['tool_name']:
                            msg['tool_name'] = row['tool_name']
                        messages.append(msg)
                    
                    return json.dumps(messages) if messages else None
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                self.cursor.execute("""
                    SELECT role, content, tool_calls, tool_call_id, tool_name 
                    FROM worker_agent_context 
                    WHERE agent_name = ? AND user_id = ? 
                    ORDER BY message_sequence ASC
                """, (agent_name, user_id))
                rows = self.cursor.fetchall()
                
                # Reconstruct messages list
                messages = []
                for row in rows:
                    msg = {
                        "role": row[0],
                        "content": row[1]
                    }
                    # Add tool_calls if present
                    if row[2]:
                        msg['tool_calls'] = json.loads(row[2])
                    # Add tool metadata for tool responses
                    if row[3]:
                        msg['tool_call_id'] = row[3]
                    if row[4]:
                        msg['tool_name'] = row[4]
                    messages.append(msg)
                
                return json.dumps(messages) if messages else None
    
    def add_context(self, agent_name, user_id, response_or_responses, purpose=None):
        """Add context for a given agent to the context table. Can handle single response or list of responses."""
        # Normalize input to always be a list
        if isinstance(response_or_responses, list):
            responses = response_or_responses
        else:
            responses = [response_or_responses]
        
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    # Ensure agent exists in directory
                    cursor.execute("""
                        INSERT INTO worker_agent_directory_v2 (agent_name, user_id, purpose)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (agent_name, user_id) 
                        DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                    """, (agent_name, user_id, purpose))
                    
                    # Get current max sequence number
                    cursor.execute("""
                        SELECT COALESCE(MAX(message_sequence), 0) 
                        FROM worker_agent_context 
                        WHERE agent_name = %s AND user_id = %s
                    """, (agent_name, user_id))
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
                        if 'tool_name' in response:
                            tool_name = response['tool_name']
                        
                        cursor.execute("""
                            INSERT INTO worker_agent_context 
                            (agent_name, user_id, message_sequence, role, content, tool_calls, tool_call_id, tool_name)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (agent_name, user_id, seq, role, content, tool_calls, tool_call_id, tool_name))
                
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                # Ensure agent exists in directory
                self.cursor.execute("""
                    INSERT OR IGNORE INTO worker_agent_directory_v2 
                    (agent_name, user_id, purpose)
                    VALUES (?, ?, ?)
                """, (agent_name, user_id, purpose))
                
                # Get the current max sequence number
                self.cursor.execute("""
                    SELECT COALESCE(MAX(message_sequence), 0) 
                    FROM worker_agent_context 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
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
                    if 'tool_name' in response:
                        tool_name = response['tool_name']
                    
                    self.cursor.execute("""
                        INSERT INTO worker_agent_context 
                        (agent_name, user_id, message_sequence, role, content, tool_calls, tool_call_id, tool_name)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (agent_name, user_id, seq, role, content, tool_calls, tool_call_id, tool_name))
                
                self.conn.commit()
    
    def create_agent(self, agent_name, user_id, purpose, initial_context=None):
        """Create a new worker agent with optional initial context."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    # Create agent in directory
                    cursor.execute("""
                        INSERT INTO worker_agent_directory_v2 (agent_name, user_id, purpose)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (agent_name, user_id) 
                        DO UPDATE SET 
                            purpose = EXCLUDED.purpose,
                            updated_at = CURRENT_TIMESTAMP
                    """, (agent_name, user_id, purpose))
                    
                    # Add initial context if provided
                    if initial_context:
                        if not isinstance(initial_context, list):
                            initial_context = [initial_context]
                        
                        for i, msg in enumerate(initial_context, 1):
                            role = msg.get('role')
                            content = msg.get('content')
                            tool_calls = json.dumps(msg['tool_calls']) if 'tool_calls' in msg else None
                            tool_call_id = msg.get('tool_call_id')
                            tool_name = msg.get('tool_name')
                            
                            cursor.execute("""
                                INSERT INTO worker_agent_context 
                                (agent_name, user_id, message_sequence, role, content, tool_calls, tool_call_id, tool_name)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (agent_name, user_id, i, role, content, tool_calls, tool_call_id, tool_name))
                
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                # Create agent in directory
                self.cursor.execute("""
                    INSERT OR REPLACE INTO worker_agent_directory_v2 
                    (agent_name, user_id, purpose)
                    VALUES (?, ?, ?)
                """, (agent_name, user_id, purpose))
                
                # Add initial context if provided
                if initial_context:
                    if not isinstance(initial_context, list):
                        initial_context = [initial_context]
                    
                    for i, msg in enumerate(initial_context, 1):
                        role = msg.get('role')
                        content = msg.get('content')
                        tool_calls = json.dumps(msg['tool_calls']) if 'tool_calls' in msg else None
                        tool_call_id = msg.get('tool_call_id')
                        tool_name = msg.get('tool_name')
                        
                        self.cursor.execute("""
                            INSERT INTO worker_agent_context 
                            (agent_name, user_id, message_sequence, role, content, tool_calls, tool_call_id, tool_name)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (agent_name, user_id, i, role, content, tool_calls, tool_call_id, tool_name))
                
                self.conn.commit()
    
    def delete_agent(self, agent_name, user_id):
        """Delete a worker agent and all its context."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cursor:
                    # Delete context first
                    cursor.execute("""
                        DELETE FROM worker_agent_context 
                        WHERE agent_name = %s AND user_id = %s
                    """, (agent_name, user_id))
                    
                    # Delete from directory
                    cursor.execute("""
                        DELETE FROM worker_agent_directory_v2 
                        WHERE agent_name = %s AND user_id = %s
                    """, (agent_name, user_id))
                    rowcount = cursor.rowcount
                conn.commit()
                return rowcount > 0
            finally:
                self.pool.putconn(conn)
        else:
            with self.lock:
                # Delete context first
                self.cursor.execute("""
                    DELETE FROM worker_agent_context 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
                
                # Delete from directory
                self.cursor.execute("""
                    DELETE FROM worker_agent_directory_v2 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
                rowcount = self.cursor.rowcount
                self.conn.commit()
                return rowcount > 0
    
    def list_agents(self, user_id):
        """List all agents for a given user from v2 table."""
        if self.db_type == 'postgres':
            conn = self.pool.getconn()
            try:
                with conn.cursor(cursor_factory=self.RealDictCursor) as cursor:
                    cursor.execute("""
                        SELECT agent_name, purpose, created_at, updated_at 
                        FROM worker_agent_directory_v2 
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
                    FROM worker_agent_directory_v2 
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

