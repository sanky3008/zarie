import os
import sqlite3
from dotenv import load_dotenv

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
        # From scripts/ -> go up 1 level to zarie/ -> go up 1 level to Donna/ -> chats.db
        # We need to be careful with paths.
        # __file__ = .../zarie/scripts/create_slack_tables.py
        # dirname = .../zarie/scripts
        # dirname(dirname) = .../zarie
        # dirname(dirname(dirname)) = .../Donna
        
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(base_dir, 'chats.db')
        print(f"Connecting to SQLite DB at: {db_path}")
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'

def create_tables():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    print(f"Creating tables in {db_type} database...")
    
    # SQL for creating slack_installations table
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS slack_installations (
        id SERIAL PRIMARY KEY,
        client_id TEXT,
        app_id TEXT,
        enterprise_id TEXT,
        enterprise_name TEXT,
        enterprise_url TEXT,
        team_id TEXT,
        team_name TEXT,
        bot_token TEXT,
        bot_id TEXT,
        bot_user_id TEXT,
        bot_scopes TEXT,
        bot_refresh_token TEXT,
        bot_token_expires_at TIMESTAMP,
        user_id TEXT,
        user_token TEXT,
        user_scopes TEXT,
        user_refresh_token TEXT,
        user_token_expires_at TIMESTAMP,
        incoming_webhook_url TEXT,
        incoming_webhook_channel TEXT,
        incoming_webhook_channel_id TEXT,
        incoming_webhook_configuration_url TEXT,
        is_enterprise_install BOOLEAN,
        token_type TEXT,
        installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    # Adjust for SQLite
    if db_type == 'sqlite':
        create_table_sql = create_table_sql.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        create_table_sql = create_table_sql.replace("TIMESTAMP DEFAULT CURRENT_TIMESTAMP", "DATETIME DEFAULT CURRENT_TIMESTAMP")
        create_table_sql = create_table_sql.replace("TIMESTAMP", "DATETIME")
        create_table_sql = create_table_sql.replace("BOOLEAN", "INTEGER")
    
    # SQL for slack_bots table
    create_bots_table_sql = """
    CREATE TABLE IF NOT EXISTS slack_bots (
        id SERIAL PRIMARY KEY,
        client_id TEXT,
        app_id TEXT,
        enterprise_id TEXT,
        enterprise_name TEXT,
        team_id TEXT,
        team_name TEXT,
        bot_token TEXT,
        bot_id TEXT,
        bot_user_id TEXT,
        bot_scopes TEXT,
        bot_refresh_token TEXT,
        bot_token_expires_at TIMESTAMP,
        is_enterprise_install BOOLEAN,
        installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    if db_type == 'sqlite':
        create_bots_table_sql = create_bots_table_sql.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        create_bots_table_sql = create_bots_table_sql.replace("TIMESTAMP DEFAULT CURRENT_TIMESTAMP", "DATETIME DEFAULT CURRENT_TIMESTAMP")
        create_bots_table_sql = create_bots_table_sql.replace("TIMESTAMP", "DATETIME")
        create_bots_table_sql = create_bots_table_sql.replace("BOOLEAN", "INTEGER")

    try:
        cursor.execute(create_table_sql)
        cursor.execute(create_bots_table_sql)
        
        # Create indexes
        if db_type == 'postgres':
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_slack_installations_team_id ON slack_installations (team_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_slack_bots_team_id ON slack_bots (team_id);")
        else:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_slack_installations_team_id ON slack_installations (team_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_slack_bots_team_id ON slack_bots (team_id);")

        conn.commit()
        print("Tables created successfully.")
    except Exception as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    create_tables()
