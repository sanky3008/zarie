import sqlite3
import os
from datetime import datetime, timedelta
from dateutil import rrule as rrule_module
from dateutil.parser import parse

def get_db_connection():
    """Get database connection"""
    database_url = os.getenv('DATABASE_URL')
    
    if database_url:
        import psycopg2
        conn = psycopg2.connect(database_url)
        return conn, 'postgres'
    else:
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'chats.db')
        conn = sqlite3.connect(db_path)
        return conn, 'sqlite'

def get_due_events():
    """Get all time events due within the next 5 minutes"""
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now()
    five_mins_later = now + timedelta(minutes=5)
    
    try:
        if db_type == 'postgres':
            cursor.execute("""
                SELECT id, agent_name, user_id, reminder_name, 
                       next_trigger_timestamp, is_recurring, 
                       recurrence_rule, message
                FROM time_events
                WHERE status = 'ACTIVE'
                AND next_trigger_timestamp <= %s
            """, (five_mins_later.isoformat(),))
            return cursor.fetchall()
        else:
            cursor.execute("""
                SELECT id, agent_name, user_id, reminder_name, 
                       next_trigger_timestamp, is_recurring, 
                       recurrence_rule, message
                FROM time_events
                WHERE status = 'ACTIVE'
                AND next_trigger_timestamp <= ?
            """, (five_mins_later.isoformat(),))
            rows = cursor.fetchall()
            return [
                {
                    'id': row[0],
                    'agent_name': row[1],
                    'user_id': row[2],
                    'reminder_name': row[3],
                    'next_trigger_timestamp': row[4],
                    'is_recurring': bool(row[5]),
                    'recurrence_rule': row[6],
                    'message': row[7]
                }
                for row in rows
            ]
    finally:
        conn.close()

def update_next_trigger(event_id, recurrence_rule):
    """Calculate and update next trigger time for recurring events"""
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Parse RRULE string
        rule_dict = {}
        for part in recurrence_rule.split(';'):
            if '=' in part:
                key, value = part.split('=', 1)
                rule_dict[key] = value
        
        # Map frequency
        freq_map = {
            'YEARLY': rrule_module.YEARLY,
            'MONTHLY': rrule_module.MONTHLY,
            'WEEKLY': rrule_module.WEEKLY,
            'DAILY': rrule_module.DAILY,
            'HOURLY': rrule_module.HOURLY,
            'MINUTELY': rrule_module.MINUTELY,
            'SECONDLY': rrule_module.SECONDLY
        }
        
        freq = freq_map.get(rule_dict.get('FREQ', 'DAILY'))
        now = datetime.now()
        
        # Generate next occurrence
        rule = rrule_module.rrule(freq, dtstart=now, count=2)
        next_occurrence = list(rule)[1]
        
        # Update database
        if db_type == 'postgres':
            cursor.execute("""
                UPDATE time_events
                SET next_trigger_timestamp = %s
                WHERE id = %s
            """, (next_occurrence.isoformat(), event_id))
        else:
            cursor.execute("""
                UPDATE time_events
                SET next_trigger_timestamp = ?
                WHERE id = ?
            """, (next_occurrence.isoformat(), event_id))
        
        conn.commit()
    finally:
        conn.close()

def disable_event(event_id):
    """Mark a one-time event as DISABLED after it's triggered"""
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if db_type == 'postgres':
            cursor.execute("""
                UPDATE time_events 
                SET status = 'DISABLED' 
                WHERE id = %s
            """, (event_id,))
        else:
            cursor.execute("""
                UPDATE time_events 
                SET status = 'DISABLED' 
                WHERE id = ?
            """, (event_id,))
        
        conn.commit()
    finally:
        conn.close()

