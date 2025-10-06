import sqlite3
import json
import threading
import os

class State:
    def __init__(self, db_path='chats.db'):
        """Initialize the State class and connect to the database."""
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
        
        # Create the table
        self._initialize_database()
    
    def __del__(self):
        """Close the database connection when the object is destroyed."""
        if hasattr(self, 'conn'):
            self.conn.close()
    
    def _initialize_database(self):
        """Create the chats table if it doesn't exist."""
        if self.db_type == 'postgres':
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    user_id TEXT PRIMARY KEY,
                    context TEXT NOT NULL
                )
            """)
        else:  # sqlite
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    user_id TEXT PRIMARY KEY,
                    context TEXT NOT NULL
                )
            """)
        self.conn.commit()
    
    def get_context(self, user_id):
        """Get the context BLOB for a given user_id."""
        with self.lock:
            if self.db_type == 'postgres':
                self.cursor.execute("SELECT context FROM chats WHERE user_id = %s", (user_id,))
            else:
                self.cursor.execute("SELECT context FROM chats WHERE user_id = ?", (user_id,))
            
            row = self.cursor.fetchone()
            
            if self.db_type == 'postgres':
                return row['context'] if row else None
            else:
                return row[0] if row else None
    
    def add_context(self, user_id, response):
        """Add context for a given user_id."""
        with self.lock:
            # Get the current context
            if self.db_type == 'postgres':
                self.cursor.execute("SELECT context FROM chats WHERE user_id = %s", (user_id,))
            else:
                self.cursor.execute("SELECT context FROM chats WHERE user_id = ?", (user_id,))
            
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
            
            # Append the response to the context
            context.append(response)
            
            # Save the updated context back to the database
            context_json = json.dumps(context)
            
            # Use INSERT OR REPLACE / UPSERT
            if self.db_type == 'postgres':
                # PostgreSQL UPSERT
                self.cursor.execute("""
                    INSERT INTO chats (user_id, context) 
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) 
                    DO UPDATE SET context = EXCLUDED.context
                """, (user_id, context_json))
            else:
                # SQLite INSERT OR REPLACE
                if context_blob:
                    self.cursor.execute(
                        "UPDATE chats SET context = ? WHERE user_id = ?",
                        (context_json, user_id)
                    )
                else:
                    self.cursor.execute(
                        "INSERT INTO chats (user_id, context) VALUES (?, ?)",
                        (user_id, context_json)
                    )
            
            self.conn.commit()
