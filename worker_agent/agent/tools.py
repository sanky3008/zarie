import sqlite3
import os
from datetime import datetime

# Import timezone helpers
from event_manager.time_event_manager import parse_ist_time, ist_to_utc

# Import shared pool from directory
from worker_agent.directory.directory import get_shared_pool

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
    """Get database connection from shared pool"""
    pool, db_type, sqlite_conn, sqlite_lock, _ = get_shared_pool()
    
    if db_type == 'postgres':
        # Return connection from pool (caller must putconn when done)
        conn = pool.getconn()
        return conn, 'postgres', None
    else:
        # For SQLite, return the shared connection and lock
        return sqlite_conn, 'sqlite', sqlite_lock

def return_db_connection(conn, db_type):
    """Return connection to pool (only needed for postgres)"""
    if db_type == 'postgres':
        pool, _, _, _, _ = get_shared_pool()
        pool.putconn(conn)


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
    conn, db_type, sqlite_lock = get_db_connection()
    
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
        timestamp_ist = parse_ist_time(next_trigger_timestamp)
        timestamp_utc = ist_to_utc(timestamp_ist)
        next_trigger_timestamp_utc = timestamp_utc.isoformat()
        
        # Use lock for SQLite operations
        if db_type == 'sqlite' and sqlite_lock:
            with sqlite_lock:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO time_events 
                    (agent_name, user_id, next_trigger_timestamp, is_recurring, 
                     recurrence_rule, reminder_name, message, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
                """, (agent_name, user_id, next_trigger_timestamp_utc, is_recurring, 
                      recurrence_rule, reminder_name, message))
                conn.commit()
        else:
            # PostgreSQL
            cursor = conn.cursor()
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
            conn.commit()
        
        return f"Time event '{reminder_name}' set successfully"
        
    except Exception as e:
        if db_type == 'postgres':
            conn.rollback()
        return f"Error setting time event: {str(e)}"
    finally:
        return_db_connection(conn, db_type)


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
    conn, db_type, sqlite_lock = get_db_connection()
    
    try:
        # Use lock for SQLite operations
        if db_type == 'sqlite' and sqlite_lock:
            with sqlite_lock:
                cursor = conn.cursor()
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
        else:
            # PostgreSQL
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE time_events 
                SET status = 'DISABLED'
                WHERE agent_name = %s AND user_id = %s AND reminder_name = %s
            """, (agent_name, user_id, reminder_name))
            
            if cursor.rowcount > 0:
                conn.commit()
                return f"Time event '{reminder_name}' deleted successfully"
            else:
                return f"Time event '{reminder_name}' not found"
            
    except Exception as e:
        if db_type == 'postgres':
            conn.rollback()
        return f"Error deleting time event: {str(e)}"
    finally:
        return_db_connection(conn, db_type)


