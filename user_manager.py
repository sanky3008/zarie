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


def create_or_update_user(telegram_id: str, first_name: str, last_name: str = None, username: str = None, platform: str = 'telegram', team_id: str = None) -> bool:
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
                INSERT INTO users (telegram_id, name, telegram_username, created_at, has_zarie, platform, team_id)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP, TRUE, %s, %s)
                ON CONFLICT (telegram_id) DO UPDATE
                SET name = EXCLUDED.name, telegram_username = EXCLUDED.telegram_username, has_zarie = TRUE, platform = EXCLUDED.platform, team_id = EXCLUDED.team_id
            """, (telegram_id, name, username, platform, team_id))
        else:
            # For SQLite, check if user exists first to preserve created_at and update has_zarie
            if user_exists(telegram_id):
                cursor.execute("""
                    UPDATE users
                    SET name = ?, telegram_username = ?, has_zarie = TRUE, platform = ?, team_id = ?
                    WHERE telegram_id = ?
                """, (name, username, platform, team_id, telegram_id))
            else:
                cursor.execute("""
                    INSERT INTO users (telegram_id, name, telegram_username, created_at, has_zarie, platform, team_id)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, TRUE, ?, ?)
                """, (telegram_id, name, username, platform, team_id))
        
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
        cursor.execute("SELECT id, telegram_id, name, telegram_username, created_at, has_zarie, platform, team_id FROM users WHERE telegram_id = %s" if db_type == 'postgres' else "SELECT id, telegram_id, name, telegram_username, created_at, has_zarie, platform, team_id FROM users WHERE telegram_id = ?", (telegram_id,))
        result = cursor.fetchone()
        
        if result:
            if db_type == 'postgres':
                return {
                    'id': result[0],
                    'telegram_id': result[1],
                    'name': result[2],
                    'telegram_username': result[3],
                    'created_at': result[4],
                    'has_zarie': result[5],
                    'platform': result[6],
                    'team_id': result[7]
                }
            else:
                return {
                    'id': result[0],
                    'telegram_id': result[1],
                    'name': result[2],
                    'telegram_username': result[3],
                    'created_at': result[4],
                    'has_zarie': bool(result[5]), # SQLite stores booleans as 0/1
                    'platform': result[6],
                    'team_id': result[7]
                }
        return None
    except Exception as e:
        print(f"Error getting user: {e}")
        return None
    finally:
        conn.close()


def set_user_blocked(telegram_id: str, blocked: bool = True) -> bool:
    """
    Set the blocked status for a user
    """
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if user exists first
        if not user_exists(telegram_id):
            print(f"User {telegram_id} not found, cannot mark as blocked")
            return False
            
        block_val = blocked
        if db_type == 'sqlite':
            block_val = 1 if blocked else 0
            
        print(f"Marking user {telegram_id} as blocked={blocked}...")
        
        if db_type == 'postgres':
            cursor.execute("UPDATE users SET is_blocked = %s WHERE telegram_id = %s", (block_val, telegram_id))
        else:
            cursor.execute("UPDATE users SET is_blocked = ? WHERE telegram_id = ?", (block_val, telegram_id))
            
        conn.commit()
        return True
    except Exception as e:
        print(f"Error setting user blocked status: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
