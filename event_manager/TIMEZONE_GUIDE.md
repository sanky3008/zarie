# Timezone Handling Guide

## Overview
- **Database Storage**: All timestamps are stored in **UTC**
- **User Interaction**: All times shown to users are in **IST (Indian Standard Time)**
- **Conversion**: Happens automatically in code

## Available Functions

### For AI Agents Setting Reminders

When a user says "Remind me at 9 AM" or "Set reminder for 3 PM tomorrow":

**Simply pass the IST time to `set_time_event()` - conversion to UTC happens automatically!**

```python
from worker_agent.agent.tools import set_time_event

# Just pass the IST timestamp directly
# The function will convert it to UTC before storing
set_time_event(
    agent_name="my_agent",
    user_id="123456",
    next_trigger_timestamp="2025-10-29 09:00:00",  # IST time
    is_recurring=False,
    reminder_name="morning_reminder",
    message="Good morning!"
)
```

The `set_time_event` function automatically:
1. Parses the timestamp as IST
2. Converts to UTC
3. Stores in UTC format in the database

### For AI Agents Showing Times to Users

When showing reminder times back to the user:

```python
from event_manager.time_event_manager import utc_to_ist

# Get UTC timestamp from database
next_trigger_utc = parse("2025-10-29 03:30:00+00:00")

# Convert to IST for display
next_trigger_ist = utc_to_ist(next_trigger_utc)

# Show to user: "Your reminder is set for 9:00 AM IST"
```

## Helper Functions Reference

### `get_ist_now()`
Returns current time in IST timezone.

### `get_utc_now()`
Returns current time in UTC timezone.

### `ist_to_utc(dt)`
Converts IST datetime to UTC.

### `utc_to_ist(dt)`
Converts UTC datetime to IST.

### `parse_ist_time(time_str)`
Parses a time string and treats it as IST if no timezone is specified.

## Example: Setting a 9 AM Daily Reminder

```python
# User says: "Remind me daily at 9 AM"
from worker_agent.agent.tools import set_time_event
from datetime import datetime

# Just pass IST time directly - conversion happens automatically
set_time_event(
    agent_name="general_reminder_agent",
    user_id="7580670088",
    next_trigger_timestamp="2025-10-29 09:00:00",  # 9 AM IST
    is_recurring=True,
    freq="DAILY",
    reminder_name="daily_morning_reminder",
    message="Good morning! Time to start your day."
)
# The function stores it as 03:30:00 UTC in the database automatically

# When showing back to user, the scheduler automatically handles UTC→IST conversion
```

## Important Notes

1. **AI Agents don't need to worry about timezones** - `set_time_event()` automatically converts IST to UTC
2. **Database always stores UTC** - This happens automatically in `set_time_event()`
3. **Users always see IST** - The scheduler logs show UTC, but users receive messages in IST context
4. **Naive datetimes** - If a datetime has no timezone info:
   - `ist_to_utc()` assumes it's IST
   - `utc_to_ist()` assumes it's UTC
5. **The scheduler** checks events using UTC, so everything stays consistent across timezones

