import sqlite3
import json
import threading
import os

class Directory:
    def __init__(self, db_path=None):
        """Initialize the Directory class and connect to the database."""
        # Default to parent directory for local development
        if db_path is None:
            # Go up three levels from directory.py -> directory/ -> worker_agent/ -> alpha-v0.1/ -> Donna/
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'chats.db')
        self.db_path = db_path
        self.lock = threading.Lock()
        
        # Check if DATABASE_URL exists (Railway PostgreSQL)
        database_url = os.getenv('DATABASE_URL')
        
        if database_url:
            # Use PostgreSQL
            import psycopg2
            from psycopg2.extras import RealDictCursor
            
            self.db_type = 'postgres'
            self.conn = psycopg2.connect(database_url)
            self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            # Use SQLite (for local development)
            self.db_type = 'sqlite'
            self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=30000")
            self.cursor = self.conn.cursor()
        
        # Table already created by migration script
    
    def __del__(self):
        """Close the database connection when the object is destroyed."""
        if hasattr(self, 'conn'):
            self.conn.close()
    
    def get_agent(self, agent_name, user_id):
        """Get the agent record for a given agent_name and user_id."""
        with self.lock:
            if self.db_type == 'postgres':
                self.cursor.execute("""
                    SELECT agent_name, user_id, purpose, context, created_at, updated_at 
                    FROM worker_agent_directory 
                    WHERE agent_name = %s AND user_id = %s
                """, (agent_name, user_id))
            else:
                self.cursor.execute("""
                    SELECT agent_name, user_id, purpose, context, created_at, updated_at 
                    FROM worker_agent_directory 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
            
            row = self.cursor.fetchone()
            
            if self.db_type == 'postgres':
                return row if row else None
            else:
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
        with self.lock:
            if self.db_type == 'postgres':
                self.cursor.execute("""
                    SELECT context FROM worker_agent_directory 
                    WHERE agent_name = %s AND user_id = %s
                """, (agent_name, user_id))
            else:
                self.cursor.execute("""
                    SELECT context FROM worker_agent_directory 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
            
            row = self.cursor.fetchone()
            
            if self.db_type == 'postgres':
                return row['context'] if row else None
            else:
                return row[0] if row else None
    
    def add_context(self, agent_name, user_id, response_or_responses, purpose=None):
        """Add context for a given agent. Can handle single response or list of responses."""
        # Normalize input to always be a list
        if isinstance(response_or_responses, list):
            responses = response_or_responses
        else:
            responses = [response_or_responses]
        
        with self.lock:
            # Get the current context
            if self.db_type == 'postgres':
                self.cursor.execute("""
                    SELECT context FROM worker_agent_directory 
                    WHERE agent_name = %s AND user_id = %s
                """, (agent_name, user_id))
            else:
                self.cursor.execute("""
                    SELECT context FROM worker_agent_directory 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
            
            row = self.cursor.fetchone()
            
            if self.db_type == 'postgres':
                context_blob = row['context'] if row else None
            else:
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
            
            # Use INSERT OR REPLACE / UPSERT
            if self.db_type == 'postgres':
                # PostgreSQL UPSERT
                self.cursor.execute("""
                    INSERT INTO worker_agent_directory (agent_name, user_id, purpose, context, updated_at) 
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (agent_name, user_id) 
                    DO UPDATE SET 
                        context = EXCLUDED.context,
                        updated_at = CURRENT_TIMESTAMP
                """, (agent_name, user_id, purpose, context_json))
            else:
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
        with self.lock:
            # Prepare initial context
            if initial_context is None:
                context = []
            elif isinstance(initial_context, list):
                context = initial_context
            else:
                context = [initial_context]
            
            context_json = json.dumps(context)
            
            # Insert new agent
            if self.db_type == 'postgres':
                self.cursor.execute("""
                    INSERT INTO worker_agent_directory (agent_name, user_id, purpose, context)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (agent_name, user_id) 
                    DO UPDATE SET 
                        purpose = EXCLUDED.purpose,
                        context = EXCLUDED.context,
                        updated_at = CURRENT_TIMESTAMP
                """, (agent_name, user_id, purpose, context_json))
            else:
                self.cursor.execute("""
                    INSERT OR REPLACE INTO worker_agent_directory (agent_name, user_id, purpose, context)
                    VALUES (?, ?, ?, ?)
                """, (agent_name, user_id, purpose, context_json))
            
            self.conn.commit()
    
    def delete_agent(self, agent_name, user_id):
        """Delete a worker agent."""
        with self.lock:
            if self.db_type == 'postgres':
                self.cursor.execute("""
                    DELETE FROM worker_agent_directory 
                    WHERE agent_name = %s AND user_id = %s
                """, (agent_name, user_id))
            else:
                self.cursor.execute("""
                    DELETE FROM worker_agent_directory 
                    WHERE agent_name = ? AND user_id = ?
                """, (agent_name, user_id))
            
            self.conn.commit()
            return self.cursor.rowcount > 0
    
    def list_agents(self, user_id):
        """List all agents for a given user."""
        with self.lock:
            if self.db_type == 'postgres':
                self.cursor.execute("""
                    SELECT agent_name, purpose, created_at, updated_at 
                    FROM worker_agent_directory 
                    WHERE user_id = %s
                    ORDER BY updated_at DESC
                """, (user_id,))
                return self.cursor.fetchall()
            else:
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

