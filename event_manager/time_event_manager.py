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
        # First, get the current next_trigger_timestamp
        if db_type == 'postgres':
            cursor.execute("""
                SELECT next_trigger_timestamp FROM time_events WHERE id = %s
            """, (event_id,))
        else:
            cursor.execute("""
                SELECT next_trigger_timestamp FROM time_events WHERE id = ?
            """, (event_id,))
        
        row = cursor.fetchone()
        if not row:
            print(f"Event {event_id} not found")
            return
        
        current_trigger = row[0] if db_type == 'postgres' else row[0]
        dtstart = parse(current_trigger) if isinstance(current_trigger, str) else current_trigger
        
        print(f"  Updating next trigger from: {dtstart}")
        print(f"  RRULE: {recurrence_rule}")
        
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
        
        # Parse additional RRULE parameters
        rrule_kwargs = {'freq': freq, 'dtstart': dtstart}
        
        if 'INTERVAL' in rule_dict:
            rrule_kwargs['interval'] = int(rule_dict['INTERVAL'])
        
        if 'BYDAY' in rule_dict:
            rrule_kwargs['byweekday'] = [rrule_module.weekday(day) for day in rule_dict['BYDAY'].split(',')]
        
        if 'BYMONTHDAY' in rule_dict:
            rrule_kwargs['bymonthday'] = [int(day) for day in rule_dict['BYMONTHDAY'].split(',')]
        
        if 'BYMONTH' in rule_dict:
            rrule_kwargs['bymonth'] = [int(month) for month in rule_dict['BYMONTH'].split(',')]
        
        if 'UNTIL' in rule_dict:
            rrule_kwargs['until'] = parse(rule_dict['UNTIL'])
        
        if 'COUNT' in rule_dict:
            rrule_kwargs['count'] = int(rule_dict['COUNT'])
        
        # Generate next occurrence using .after() method (much more efficient!)
        try:
            rule = rrule_module.rrule(**rrule_kwargs)
            # Use .after() to get the next occurrence after dtstart
            next_occurrence = rule.after(dtstart)
            
            if next_occurrence is None:
                print(f"  Warning: No next occurrence found, using fallback")
                from datetime import timedelta
                next_occurrence = dtstart + timedelta(days=1)
        except Exception as e:
            print(f"  Error calculating RRULE: {e}")
            # Fallback: add 1 day
            from datetime import timedelta
            next_occurrence = dtstart + timedelta(days=1)
        
        print(f"  Next occurrence: {next_occurrence}")
        
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
        print(f"  ✓ Updated next trigger to {next_occurrence}")
    except Exception as e:
        print(f"  ✗ Error updating next trigger: {e}")
        import traceback
        traceback.print_exc()
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

