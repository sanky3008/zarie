"""
User management module for handling user data in the database
Supports both SQLite (local) and PostgreSQL (Railway)
"""
import os
import sqlite3
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def _migrate_db(conn, db_type):
    """Ensure the users table has the timezone column."""
    cursor = conn.cursor()
    try:
        # Check if timezone column exists
        if db_type == 'postgres':
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='users' AND column_name='timezone';
            """)
            if not cursor.fetchone():
                print("Migrating DB: Adding timezone column (Postgres)...")
                cursor.execute("ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'Asia/Kolkata';")
                conn.commit()
        else:
            # SQLite
            cursor.execute("PRAGMA table_info(users)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'timezone' not in columns:
                print("Migrating DB: Adding timezone column (SQLite)...")
                cursor.execute("ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'Asia/Kolkata'")
                conn.commit()
    except Exception as e:
        print(f"Migration warning: {e}")
        conn.rollback()

    try:
        # Check for has_welcomed column
        if db_type == 'postgres':
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='users' AND column_name='has_welcomed';
            """)
            if not cursor.fetchone():
                print("Migrating DB: Adding has_welcomed column (Postgres)...")
                cursor.execute("ALTER TABLE users ADD COLUMN has_welcomed BOOLEAN DEFAULT FALSE;")
                conn.commit()
        else:
            # SQLite
            cursor.execute("PRAGMA table_info(users)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'has_welcomed' not in columns:
                print("Migrating DB: Adding has_welcomed column (SQLite)...")
                cursor.execute("ALTER TABLE users ADD COLUMN has_welcomed INTEGER DEFAULT 0")
                conn.commit()
    except Exception as e:
        print(f"Migration warning (has_welcomed): {e}")
        conn.rollback()

    try:
        # Create google_credentials table if not exists
        create_query = """
            CREATE TABLE IF NOT EXISTS google_credentials (
                user_id TEXT PRIMARY KEY,
                access_token TEXT,
                refresh_token TEXT,
                token_uri TEXT,
                client_id TEXT,
                client_secret TEXT,
                scopes TEXT,
                expiry TEXT
            );
        """
        cursor.execute(create_query)
        conn.commit()
    except Exception as e:
        print(f"Migration warning (google_creds): {e}")
        conn.rollback()


def get_db_connection():
    """Get database connection - respects ENV variable for safety"""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    conn = None
    db_type = 'sqlite'

    # Only use postgres if ENV=PROD and DATABASE_URL is set
    if env == 'PROD' and database_url:
        import psycopg2
        conn = psycopg2.connect(database_url)
        db_type = 'postgres'
    else:
        # Use SQLite for local development
        # From user_manager.py (alpha-v0.1/) -> go up 2 levels to Donna/ -> chats.db
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'chats.db')
        conn = sqlite3.connect(db_path)
        db_type = 'sqlite'
    
    # Run simple migration check
    _migrate_db(conn, db_type)
    
    return conn, db_type


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


def create_or_update_user(telegram_id: str, first_name: str, last_name: str = None, username: str = None, platform: str = 'telegram', team_id: str = None, timezone: str = None) -> bool:
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
            if timezone:
                 cursor.execute("""
                    INSERT INTO users (telegram_id, name, telegram_username, created_at, has_zarie, platform, team_id, timezone)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP, TRUE, %s, %s, %s)
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET name = EXCLUDED.name, telegram_username = EXCLUDED.telegram_username, has_zarie = TRUE, platform = EXCLUDED.platform, team_id = EXCLUDED.team_id, timezone = EXCLUDED.timezone
                """, (telegram_id, name, username, platform, team_id, timezone))
            else:
                # Don't overwrite timezone if not provided
                 cursor.execute("""
                    INSERT INTO users (telegram_id, name, telegram_username, created_at, has_zarie, platform, team_id)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP, TRUE, %s, %s)
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET name = EXCLUDED.name, telegram_username = EXCLUDED.telegram_username, has_zarie = TRUE, platform = EXCLUDED.platform, team_id = EXCLUDED.team_id
                """, (telegram_id, name, username, platform, team_id))

        else:
            # For SQLite, check if user exists first to preserve created_at and update has_zarie
            if user_exists(telegram_id):
                if timezone:
                    cursor.execute("""
                        UPDATE users
                        SET name = ?, telegram_username = ?, has_zarie = TRUE, platform = ?, team_id = ?, timezone = ?
                        WHERE telegram_id = ?
                    """, (name, username, platform, team_id, timezone, telegram_id))
                else:
                    cursor.execute("""
                        UPDATE users
                        SET name = ?, telegram_username = ?, has_zarie = TRUE, platform = ?, team_id = ?
                        WHERE telegram_id = ?
                    """, (name, username, platform, team_id, telegram_id))
            else:
                cursor.execute("""
                    INSERT INTO users (telegram_id, name, telegram_username, created_at, has_zarie, platform, team_id, timezone)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, TRUE, ?, ?, ?)
                """, (telegram_id, name, username, platform, team_id, timezone or 'Asia/Kolkata'))
        
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
        cursor.execute("SELECT id, telegram_id, name, telegram_username, created_at, has_zarie, platform, team_id, timezone, has_welcomed FROM users WHERE telegram_id = %s" if db_type == 'postgres' else "SELECT id, telegram_id, name, telegram_username, created_at, has_zarie, platform, team_id, timezone, has_welcomed FROM users WHERE telegram_id = ?", (telegram_id,))
        result = cursor.fetchone()
        
        if result:
            timezone_val = result[8] if len(result) > 8 and result[8] else 'Asia/Kolkata'
            
            if db_type == 'postgres':
                return {
                    'id': result[0],
                    'telegram_id': result[1],
                    'name': result[2],
                    'telegram_username': result[3],
                    'created_at': result[4],
                    'has_zarie': result[5],
                    'platform': result[6],
                    'team_id': result[7],
                    'timezone': timezone_val,
                    'has_welcomed': result[9] if len(result) > 9 else False
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
                    'team_id': result[7],
                    'timezone': timezone_val,
                    'has_welcomed': bool(result[9]) if len(result) > 9 else False
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


def set_user_welcomed(telegram_id: str) -> bool:
    """
    Mark a user as having received the welcome message.
    """
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        val = True if db_type == 'postgres' else 1
        
        if db_type == 'postgres':
            cursor.execute("UPDATE users SET has_welcomed = %s WHERE telegram_id = %s", (val, telegram_id))
        else:
            cursor.execute("UPDATE users SET has_welcomed = ? WHERE telegram_id = ?", (val, telegram_id))
            
        conn.commit()
        return True
    except Exception as e:
        print(f"Error setting user has_welcomed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def store_google_credentials(user_id: str, creds_data: dict) -> bool:
    """
    Store Google OAuth credentials for a user.
    creds_data should contain: token, refresh_token, token_uri, client_id, client_secret, scopes, expiry
    """
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Convert scopes list to string if needed
        scopes = creds_data.get('scopes')
        if isinstance(scopes, list):
            scopes = ','.join(scopes)
            
        if db_type == 'postgres':
            cursor.execute("""
                INSERT INTO google_credentials (user_id, access_token, refresh_token, token_uri, client_id, client_secret, scopes, expiry)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    token_uri = EXCLUDED.token_uri,
                    client_id = EXCLUDED.client_id,
                    client_secret = EXCLUDED.client_secret,
                    scopes = EXCLUDED.scopes,
                    expiry = EXCLUDED.expiry
            """, (user_id, creds_data.get('token'), creds_data.get('refresh_token'), 
                  creds_data.get('token_uri'), creds_data.get('client_id'), 
                  creds_data.get('client_secret'), scopes, creds_data.get('expiry')))
        else:
            # SQLite upsert
            cursor.execute("""
                INSERT OR REPLACE INTO google_credentials (user_id, access_token, refresh_token, token_uri, client_id, client_secret, scopes, expiry)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, creds_data.get('token'), creds_data.get('refresh_token'), 
                  creds_data.get('token_uri'), creds_data.get('client_id'), 
                  creds_data.get('client_secret'), scopes, creds_data.get('expiry')))
            
        conn.commit()
        return True
    except Exception as e:
        print(f"Error storing Google credentials: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_google_credentials(user_id: str):
    """
    Retrieve Google OAuth credentials for a user.
    Returns a dict compatible with google.oauth2.credentials.Credentials
    """
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        query = "SELECT access_token, refresh_token, token_uri, client_id, client_secret, scopes, expiry FROM google_credentials WHERE user_id = %s" if db_type == 'postgres' else "SELECT access_token, refresh_token, token_uri, client_id, client_secret, scopes, expiry FROM google_credentials WHERE user_id = ?"
        cursor.execute(query, (user_id,))
        row = cursor.fetchone()
        
        if row:
            return {
                'token': row[0],
                'refresh_token': row[1],
                'token_uri': row[2],
                'client_id': row[3],
                'client_secret': row[4],
                'scopes': row[5].split(',') if row[5] else [],
                'expiry': row[6]
            }
        return None
    except Exception as e:
        print(f"Error retrieving Google credentials: {e}")
        return None
    finally:
        conn.close()
