import unittest
import sqlite3
import os
import shutil
from user_manager import get_db_connection, store_google_credentials, get_google_credentials, _migrate_db

class TestGoogleDB(unittest.TestCase):
    def setUp(self):
        # Use a separate test DB
        self.test_db_path = "test_chats.db"
        # Patch user_manager to use this DB path? 
        # Actually user_manager.py uses os.path.join(..., 'chats.db') relative to its location.
        # For testing purposes, we might need to rely on the fact that we can manipulate the connection 
        # OR we modify get_db_connection to be more testable.
        # But for now, let's assume we can mock or just verify the functions if they accept connection? 
        # No, they call get_db_connection internally.
        # Let's mock sqlite3.connect? 
        # Or simpler: verify logic by inspecting the actual DB file if we run locally?
        # Actually, let's just use the functions and expect them to work on the local DB (dev mode).
        # But that might pollute dev DB. 
        # Ideally user_manager should allow injecting db path.
        # Given existing code: db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'chats.db')
        # We can mock os.path.dirname to point to a temp dir?
        pass

    def test_schema_migration(self):
        """Test that google_credentials table is created."""
        conn = sqlite3.connect(":memory:")
        # We can't easily test _migrate_db directly without modifying the code to accept a conn, 
        # but _migrate_db IS defined to accept (conn, db_type).
        
        # Run migration
        _migrate_db(conn, 'sqlite')
        
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='google_credentials'")
        self.assertIsNotNone(cursor.fetchone(), "google_credentials table was not created")
        
        # Check columns
        cursor.execute("PRAGMA table_info(google_credentials)")
        columns = {info[1] for info in cursor.fetchall()}
        expected = {'user_id', 'access_token', 'refresh_token', 'token_uri', 'client_id', 'client_secret', 'scopes', 'expiry'}
        self.assertTrue(expected.issubset(columns), f"Missing columns. Found: {columns}")
        conn.close()

    def test_store_and_retrieve(self):
        """Test storing and retrieving credentials."""
        import tempfile
        from unittest.mock import patch
        
        # Create a temp file for DB
        fd, temp_db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd) # Close file handle, let sqlite open it
        
        try:
            # Initialize DB with migration
            conn = sqlite3.connect(temp_db_path)
            _migrate_db(conn, 'sqlite')
            conn.close()
            
            # Helper to retrieve connection to this temp DB
            def get_temp_conn():
                return sqlite3.connect(temp_db_path), 'sqlite'
            
            with patch('user_manager.get_db_connection', side_effect=get_temp_conn):
                user_id = "test_user_1"
                creds = {
                    'token': 'access_123',
                    'refresh_token': 'refresh_123',
                    'token_uri': 'http://oauth',
                    'client_id': 'cid',
                    'client_secret': 'csec',
                    'scopes': ['email', 'calendar'],
                    'expiry': '2025-01-01'
                }
                
                # 1. Store
                result = store_google_credentials(user_id, creds)
                self.assertTrue(result)
                
                # 2. Retrieve
                retrieved = get_google_credentials(user_id)
                self.assertIsNotNone(retrieved)
                self.assertEqual(retrieved['token'], 'access_123')
                self.assertEqual(retrieved['scopes'], ['email', 'calendar'])
                
                # 3. Update
                creds['token'] = 'access_456'
                store_google_credentials(user_id, creds)
                updated = get_google_credentials(user_id)
                self.assertEqual(updated['token'], 'access_456')
                
        finally:
            if os.path.exists(temp_db_path):
                os.remove(temp_db_path)

if __name__ == '__main__':
    unittest.main()
