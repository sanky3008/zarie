import sqlite3
import os
from datetime import datetime

# Import timezone helpers
from event_manager.time_event_manager import parse_ist_time, ist_to_utc

# Optional imports
PERPLEXITY_AVAILABLE = False
try:
    from perplexity import Perplexity
    PERPLEXITY_AVAILABLE = True
except ImportError:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def get_db_connection():
    """Get database connection using the same approach as state.py"""
    database_url = os.getenv('DATABASE_URL')
    
    if database_url:
        # Use PostgreSQL for Railway deployment
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(database_url)
        return conn, 'postgres'
    else:
        # Use SQLite for local development
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '..', 'chats.db')
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn, 'sqlite'


def web_search(query: str):
    """
    Perform a web search using Perplexity API.
    
    Args:
        query (str): The search query
        
    Returns:
        str: Search results from Perplexity
    """
    client = Perplexity()
    
    completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": query,
            }
        ],
        model="sonar",
    )
    
    return completion.choices[0].message.content


def set_time_event(agent_name: str, user_id: str, next_trigger_timestamp: str, 
                  is_recurring: bool, freq: str = None, interval: int = None, 
                  until: str = None, count: int = None, byweekday: str = None,
                  bymonthday: int = None, bymonth: int = None,
                  reminder_name: str = None, message: str = ""):
    """
    Set a time event/reminder for the worker agent.
    
    Args:
        agent_name: Name of the agent
        user_id: User ID
        next_trigger_timestamp: Next trigger time in IST (ISO format) - will be converted to UTC for storage
        is_recurring: Whether this is a recurring event
        freq: Frequency (YEARLY, MONTHLY, WEEKLY, DAILY, HOURLY, MINUTELY, SECONDLY) - optional if is_recurring is True
        interval: Interval between occurrences - optional, defaults to 1 if not specified
        until: End date (ISO format) - optional
        count: Number of occurrences - optional
        byweekday: Days of week (MO,TU,WE,TH,FR,SA,SU) - optional
        bymonthday: Day of month (1-31) - optional
        bymonth: Month (1-12) - optional
        reminder_name: Name for the reminder
        message: Message to send when triggered
        
    Returns:
        str: Success message
    """
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Generate recurrence rule if recurring
        recurrence_rule = None
        if is_recurring:
            rule_parts = []
            if freq:
                rule_parts.append(f"FREQ={freq}")
            if interval is not None:
                rule_parts.append(f"INTERVAL={interval}")
            if until:
                rule_parts.append(f"UNTIL={until}")
            if count is not None:
                rule_parts.append(f"COUNT={count}")
            if byweekday:
                rule_parts.append(f"BYDAY={byweekday}")
            if bymonthday is not None:
                rule_parts.append(f"BYMONTHDAY={bymonthday}")
            if bymonth is not None:
                rule_parts.append(f"BYMONTH={bymonth}")
            recurrence_rule = ";".join(rule_parts) if rule_parts else None
        
        # Convert timestamp from IST to UTC for storage
        # Parse the timestamp (assuming IST if no timezone info)
        timestamp_ist = parse_ist_time(next_trigger_timestamp)
        timestamp_utc = ist_to_utc(timestamp_ist)
        # Store as ISO format string
        next_trigger_timestamp_utc = timestamp_utc.isoformat()
        
        # Insert or update time event
        if db_type == 'postgres':
            cursor.execute("""
                INSERT INTO time_events 
                (agent_name, user_id, next_trigger_timestamp, is_recurring, 
                 recurrence_rule, reminder_name, message, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'ACTIVE')
                ON CONFLICT (agent_name, reminder_name, user_id) 
                DO UPDATE SET 
                    next_trigger_timestamp = EXCLUDED.next_trigger_timestamp,
                    is_recurring = EXCLUDED.is_recurring,
                    recurrence_rule = EXCLUDED.recurrence_rule,
                    message = EXCLUDED.message,
                    status = 'ACTIVE'
            """, (agent_name, user_id, next_trigger_timestamp_utc, is_recurring, 
                  recurrence_rule, reminder_name, message))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO time_events 
                (agent_name, user_id, next_trigger_timestamp, is_recurring, 
                 recurrence_rule, reminder_name, message, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
            """, (agent_name, user_id, next_trigger_timestamp_utc, is_recurring, 
                  recurrence_rule, reminder_name, message))
        
        conn.commit()
        return f"Time event '{reminder_name}' set successfully"
        
    except Exception as e:
        conn.rollback()
        return f"Error setting time event: {str(e)}"
    finally:
        conn.close()


def delete_time_event(agent_name: str, user_id: str, reminder_name: str):
    """
    Delete (disable) a time event/reminder.
    
    Args:
        agent_name: Name of the agent
        user_id: User ID
        reminder_name: Name of the reminder to delete
        
    Returns:
        str: Success message
    """
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if db_type == 'postgres':
            cursor.execute("""
                UPDATE time_events 
                SET status = 'DISABLED'
                WHERE agent_name = %s AND user_id = %s AND reminder_name = %s
            """, (agent_name, user_id, reminder_name))
        else:
            cursor.execute("""
                UPDATE time_events 
                SET status = 'DISABLED'
                WHERE agent_name = ? AND user_id = ? AND reminder_name = ?
            """, (agent_name, user_id, reminder_name))
        
        if cursor.rowcount > 0:
            conn.commit()
            return f"Time event '{reminder_name}' deleted successfully"
        else:
            return f"Time event '{reminder_name}' not found"
            
    except Exception as e:
        conn.rollback()
        return f"Error deleting time event: {str(e)}"
    finally:
        conn.close()


