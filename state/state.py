import sqlite3
import json
import threading

class State:
    def __init__(self, db_path='chats.db'):
        """Initialize the State class and connect to the chats database."""
        self.db_path = db_path
        # Use thread-safe connection with WAL mode for concurrent reads/writes
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        # Enable WAL mode for better concurrent access
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.cursor = self.conn.cursor()
        self.lock = threading.Lock()
    
    def __del__(self):
        """Close the database connection when the object is destroyed."""
        if hasattr(self, 'conn'):
            self.conn.close()
    
    def get_context(self, user_id):
        """Get the context BLOB for a given user_id."""
        with self.lock:
            self.cursor.execute("SELECT context FROM chats WHERE user_id = ?", (user_id,))
            row = self.cursor.fetchone()
            return row[0] if row else None
    
    def add_context(self, user_id, response):
        """Add context for a given user_id."""
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
            
            # Append the response to the context
            context.append(response)
            
            # Save the updated context back to the database
            context_json = json.dumps(context)
            
            # Use INSERT OR REPLACE to handle both new and existing users
            if context_blob:
                # Update existing record
                self.cursor.execute(
                    "UPDATE chats SET context = ? WHERE user_id = ?",
                    (context_json, user_id)
                )
            else:
                # Insert new record
                self.cursor.execute(
                    "INSERT INTO chats (user_id, context) VALUES (?, ?)",
                    (user_id, context_json)
                )
            self.conn.commit()
