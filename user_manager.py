"""
User management module for handling user data in the database
Supports both SQLite (local) and PostgreSQL (Railway)
"""
import os
import sqlite3
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_db_connection():
    """Get database connection - respects ENV variable for safety"""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    # Only use postgres if ENV=PROD and DATABASE_URL is set
    if env == 'PROD' and database_url:
        import psycopg2
        conn = psycopg2.connect(database_url)
        return conn, 'postgres'
    else:
        # Use SQLite for local development
        # From user_manager.py (alpha-v0.1/) -> go up 2 levels to Donna/ -> chats.db
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'chats.db')
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'


def user_exists(telegram_id: str) -> bool:
    """Check if a user exists in the database by telegram_id"""
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id FROM users WHERE telegram_id = %s" if db_type == 'postgres' else "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
        result = cursor.fetchone()
        return result is not None
    except Exception as e:
        print(f"Error checking if user exists: {e}")
        return False
    finally:
        conn.close()


def create_or_update_user(telegram_id: str, first_name: str, last_name: str = None, username: str = None) -> bool:
    """
    Create a new user or update existing user in the database
    Returns True if successful, False otherwise
    """
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    # Combine first_name and last_name
    name = first_name
    if last_name:
        name = f"{first_name} {last_name}"
    
    try:
        if db_type == 'postgres':
            # Use INSERT ... ON CONFLICT for PostgreSQL (upsert)
            cursor.execute("""
                INSERT INTO users (telegram_id, name, telegram_username, created_at, has_zarie)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP, TRUE)
                ON CONFLICT (telegram_id) DO UPDATE
                SET name = EXCLUDED.name, telegram_username = EXCLUDED.telegram_username, has_zarie = TRUE
            """, (telegram_id, name, username))
        else:
            # For SQLite, check if user exists first to preserve created_at and update has_zarie
            if user_exists(telegram_id):
                cursor.execute("""
                    UPDATE users
                    SET name = ?, telegram_username = ?, has_zarie = TRUE
                    WHERE telegram_id = ?
                """, (name, username, telegram_id))
            else:
                cursor.execute("""
                    INSERT INTO users (telegram_id, name, telegram_username, created_at, has_zarie)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, TRUE)
                """, (telegram_id, name, username))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"Error creating/updating user: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_user(telegram_id: str):
    """Get user information by telegram_id"""
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id, telegram_id, name, telegram_username, created_at FROM users WHERE telegram_id = %s" if db_type == 'postgres' else "SELECT id, telegram_id, name, telegram_username, created_at FROM users WHERE telegram_id = ?", (telegram_id,))
        result = cursor.fetchone()
        
        if result:
            if db_type == 'postgres':
                return {
                    'id': result[0],
                    'telegram_id': result[1],
                    'name': result[2],
                    'telegram_username': result[3],
                    'created_at': result[4]
                }
            else:
                return {
                    'id': result[0],
                    'telegram_id': result[1],
                    'name': result[2],
                    'telegram_username': result[3],
                    'created_at': result[4]
                }
        return None
    except Exception as e:
        print(f"Error getting user: {e}")
        return None
    finally:
        conn.close()

