"""
Migrate user info from chats_context table to users table
Fetches name and username from Telegram API
"""
import os
import asyncio
import sqlite3
from dotenv import load_dotenv
from telegram.ext import Application

load_dotenv()


def get_db_connection():
    """Get database connection"""
    env = os.getenv('ENV', 'LOCAL').upper()
    database_url = os.getenv('DATABASE_URL')
    
    if env == 'PROD' and database_url:
        import psycopg2
        conn = psycopg2.connect(database_url)
        return conn, 'postgres'
    else:
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
            'chats.db'
        )
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'


async def migrate_users():
    """Migrate user info from chats_context to users table"""
    
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    # Get all unique telegram_ids from chats_context
    cursor.execute("SELECT DISTINCT user_id FROM chats_context")
    user_ids = [row[0] for row in cursor.fetchall()]
    
    print(f"Found {len(user_ids)} unique users to migrate")
    
    # Setup Telegram bot
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    app = Application.builder().token(token).build()
    bot = app.bot
    await bot.initialize()
    
    migrated = 0
    errors = 0
    
    for user_id in user_ids:
        name = None
        username = None
        
        try:
            chat = await bot.get_chat(chat_id=int(user_id))
            name = f"{chat.first_name or ''} {chat.last_name or ''}".strip() or None
            username = chat.username
            status = f"{name or 'N/A'} (@{username or 'N/A'})"
        except Exception as e:
            status = f"Not found: {e}"
            errors += 1
        
        # Insert regardless (with null if chat not found)
        try:
            if db_type == 'postgres':
                cursor.execute("""
                    INSERT INTO users (telegram_id, name, telegram_username)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET name = EXCLUDED.name, telegram_username = EXCLUDED.telegram_username
                """, (user_id, name, username))
            else:
                cursor.execute("""
                    INSERT OR REPLACE INTO users (telegram_id, name, telegram_username)
                    VALUES (?, ?, ?)
                """, (user_id, name, username))
            
            conn.commit()
            print(f"✓ {user_id}: {status}")
            migrated += 1
        except Exception as e:
            print(f"✗ {user_id}: DB error - {e}")
            errors += 1
    
    await bot.shutdown()
    conn.close()
    
    print(f"\n✅ Migrated: {migrated}, Errors: {errors}")


if __name__ == "__main__":
    asyncio.run(migrate_users())

