import sqlite3
import os
from datetime import datetime, timedelta
from dateutil import rrule as rrule_module
from dateutil.parser import parse
import pytz

# Timezone constants
IST = pytz.timezone('Asia/Kolkata')
UTC = pytz.UTC

# Module-level variables for connection pool
_pool = None
_db_type = None
_sqlite_conn = None

def get_ist_now():
    """Get current time in IST"""
    return datetime.now(IST)

def get_utc_now():
    """Get current time in UTC"""
    return datetime.now(UTC)

def ist_to_utc(dt):
    """Convert IST datetime to UTC"""
    if dt.tzinfo is None:
        # Assume naive datetime is IST
        dt = IST.localize(dt)
    return dt.astimezone(UTC)

def utc_to_ist(dt):
    """Convert UTC datetime to IST"""
    if dt.tzinfo is None:
        # Assume naive datetime is UTC
        dt = UTC.localize(dt)
    return dt.astimezone(IST)

def parse_ist_time(time_str):
    """Parse a time string and return as IST datetime"""
    dt = parse(time_str)
    if dt.tzinfo is None:
        # If no timezone info, treat as IST
        dt = IST.localize(dt)
    return dt

def _initialize_pool():
    """Initialize the connection pool for event manager"""
    global _pool, _db_type, _sqlite_conn
    
    if _pool is not None or _sqlite_conn is not None:
        return  # Already initialized
    
    database_url = os.getenv('DATABASE_URL')
    env = os.getenv('ENV', 'LOCAL').upper()
    
    if env == 'PROD' and database_url:
        # Use PostgreSQL with connection pool
        import psycopg2.pool
        _db_type = 'postgres'
        _pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=database_url)
    else:
        # Use SQLite for local development
        _db_type = 'sqlite'
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'chats.db')
        print(f"DEBUG: Connecting to SQLite DB at: {os.path.abspath(db_path)}")
        _sqlite_conn = sqlite3.connect(db_path)

def get_db_connection():
    """Get database connection from pool"""
    _initialize_pool()
    
    if _db_type == 'postgres':
        # Return connection from pool (caller must putconn when done)
        conn = _pool.getconn()
        return conn, 'postgres'
    else:
        # For SQLite, return the shared connection
        return _sqlite_conn, 'sqlite'

def return_db_connection(conn, db_type):
    """Return connection to pool (only needed for postgres)"""
    if db_type == 'postgres' and _pool is not None:
        _pool.putconn(conn)

def get_due_events():
    """Get all time events that are due now or in the past (using UTC)"""
    conn, db_type = get_db_connection()
    
    # Use UTC for database comparisons
    # Since we check every minute, only get events due NOW (not future events)
    now_utc = get_utc_now()
    
    try:
        cursor = conn.cursor()
        
        if db_type == 'postgres':
            cursor.execute("""
                SELECT t.id, t.agent_name, t.user_id, t.reminder_name, 
                       t.next_trigger_timestamp, t.is_recurring, 
                       t.recurrence_rule, t.message
                FROM time_events t
                JOIN users u ON t.user_id = u.telegram_id
                WHERE t.status = 'ACTIVE'
                AND t.next_trigger_timestamp <= %s
                AND u.has_zarie = TRUE
            """, (now_utc.isoformat(),))
            rows = cursor.fetchall()
            raw_events = [
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
        else:
            cursor.execute("""
                SELECT t.id, t.agent_name, t.user_id, t.reminder_name, 
                       t.next_trigger_timestamp, t.is_recurring, 
                       t.recurrence_rule, t.message
                FROM time_events t
                JOIN users u ON t.user_id = u.telegram_id
                WHERE t.status = 'ACTIVE'
                AND t.next_trigger_timestamp <= ?
                AND u.has_zarie = 1
            """, (now_utc.isoformat(),))
            rows = cursor.fetchall()
            raw_events = [
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
        
        # Combine events with same user_id and agent_name, separated by recurring status
        combined_events = {}
        for event in raw_events:
            key = (event['user_id'], event['agent_name'])
            
            if key not in combined_events:
                combined_events[key] = {
                    'agent_name': event['agent_name'],
                    'user_id': event['user_id'],
                    'reminders': {
                        'recurring': [],
                        'non_recurring': []
                    }
                }
            
            # Create reminder object with all relevant details
            reminder_obj = {
                'id': event['id'],
                'reminder_name': event['reminder_name'],
                'message': event['message'],
                'is_recurring': event['is_recurring'],
                'recurrence_rule': event['recurrence_rule'],
                'next_trigger_timestamp': event['next_trigger_timestamp']
            }
            
            # Add to appropriate list
            if event['is_recurring'] and event['recurrence_rule']:
                combined_events[key]['reminders']['recurring'].append(reminder_obj)
            else:
                combined_events[key]['reminders']['non_recurring'].append(reminder_obj)
        
        return list(combined_events.values())
    finally:
        return_db_connection(conn, db_type)

def update_next_trigger(event_id, recurrence_rule):
    """Calculate and update next trigger time for recurring events
    Returns: True if event is still active, False if it was disabled"""
    conn, db_type = get_db_connection()
    
    try:
        cursor = conn.cursor()
        
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
            return False
        
        current_trigger = row[0] if db_type == 'postgres' else row[0]
        dtstart = parse(current_trigger) if isinstance(current_trigger, str) else current_trigger
        
        # Ensure dtstart is timezone-aware (UTC)
        if dtstart.tzinfo is None:
            dtstart = UTC.localize(dtstart)
        elif dtstart.tzinfo != UTC:
            dtstart = dtstart.astimezone(UTC)
        
        print(f"  Updating next trigger from: {dtstart} UTC")
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
            # Map string abbreviations to rrule weekday constants
            weekday_map = {
                'MO': rrule_module.MO,
                'TU': rrule_module.TU,
                'WE': rrule_module.WE,
                'TH': rrule_module.TH,
                'FR': rrule_module.FR,
                'SA': rrule_module.SA,
                'SU': rrule_module.SU
            }
            rrule_kwargs['byweekday'] = [weekday_map[day.strip()] for day in rule_dict['BYDAY'].split(',')]
        
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
                print(f"  Warning: No next occurrence found, disabling event")
                disable_event(event_id)
                return False
        except Exception as e:
            print(f"  Error calculating RRULE: {e}")
            # Fallback: add 1 day
            next_occurrence = dtstart + timedelta(days=1)
        
        # Ensure next_occurrence is timezone-aware (UTC)
        if next_occurrence.tzinfo is None:
            next_occurrence = UTC.localize(next_occurrence)
        elif next_occurrence.tzinfo != UTC:
            next_occurrence = next_occurrence.astimezone(UTC)
        
        # If next_occurrence is still in the past (e.g., missed reminders), 
        # calculate from NOW instead to avoid rapid re-triggering
        now_utc = get_utc_now()
        if next_occurrence <= now_utc:
            print(f"  Warning: Next occurrence {next_occurrence} is in the past!")
            # Calculate next occurrence from NOW instead of from dtstart
            try:
                next_occurrence = rule.after(now_utc)
                if next_occurrence is None:
                    # No more occurrences (likely due to COUNT/UNTIL)
                    print(f"  No future occurrences available, disabling event")
                    disable_event(event_id)
                    return False
                print(f"  Adjusted to next future occurrence: {next_occurrence} UTC")
            except Exception as e:
                print(f"  Error recalculating from now: {e}")
                # Only use fallback if there's no COUNT restriction
                if 'COUNT' not in rule_dict:
                    interval = rrule_kwargs.get('interval', 1)
                    next_occurrence = now_utc + timedelta(minutes=interval)
                else:
                    # If COUNT exists and we hit an error, disable the event
                    print(f"  Error with COUNT-based rule, disabling event")
                    disable_event(event_id)
                    return False
        
        print(f"  Next occurrence: {next_occurrence} UTC")
        print(f"  Next occurrence IST: {utc_to_ist(next_occurrence)}")
        
        # Decrement COUNT if it exists (this occurrence has been processed)
        updated_recurrence_rule = recurrence_rule
        if 'COUNT' in rule_dict:
            current_count = int(rule_dict['COUNT'])
            print(f"  Current COUNT: {current_count}")
            
            # Decrement the count
            new_count = current_count - 1
            
            if new_count <= 0:
                # No more occurrences left after this one
                print(f"  COUNT exhausted, disabling event")
                disable_event(event_id)
                return False
            
            # Update the COUNT in the rule_dict and rebuild the RRULE string
            rule_dict['COUNT'] = str(new_count)
            print(f"  Decremented COUNT to: {new_count}")
            
            # Rebuild the recurrence_rule string
            updated_recurrence_rule = ';'.join([f"{k}={v}" for k, v in rule_dict.items()])
            print(f"  Updated RRULE: {updated_recurrence_rule}")
        
        # Update database with both next_trigger_timestamp and updated recurrence_rule
        if db_type == 'postgres':
            cursor.execute("""
                UPDATE time_events
                SET next_trigger_timestamp = %s,
                    recurrence_rule = %s
                WHERE id = %s
            """, (next_occurrence.isoformat(), updated_recurrence_rule, event_id))
        else:
            cursor.execute("""
                UPDATE time_events
                SET next_trigger_timestamp = ?,
                    recurrence_rule = ?
                WHERE id = ?
            """, (next_occurrence.isoformat(), updated_recurrence_rule, event_id))
        
        conn.commit()
        print(f"  ✓ Updated next trigger to {next_occurrence}")
        return True
    except Exception as e:
        print(f"  ✗ Error updating next trigger: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        return_db_connection(conn, db_type)

def disable_event(event_id):
    """Mark a one-time event as DISABLED after it's triggered"""
    conn, db_type = get_db_connection()
    
    try:
        cursor = conn.cursor()
        
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
        return_db_connection(conn, db_type)

def update_event_status(event_id, status):
    """Update the status of a time event"""
    conn, db_type = get_db_connection()
    
    try:
        cursor = conn.cursor()
        
        if db_type == 'postgres':
            cursor.execute("""
                UPDATE time_events 
                SET status = %s 
                WHERE id = %s
            """, (status, event_id))
        else:
            cursor.execute("""
                UPDATE time_events 
                SET status = ? 
                WHERE id = ?
            """, (status, event_id))
        
        conn.commit()
        # print(f"  ✓ Updated status to {status} for event {event_id}")
    except Exception as e:
        print(f"  ✗ Error updating status for event {event_id}: {e}")
    finally:
        return_db_connection(conn, db_type)

