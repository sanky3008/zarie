import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional

class MessageBuffer:
    """
    Manages message buffering and debouncing.
    Stores messages for a given key and schedules a processing task.
    """
    def __init__(self, process_callback, debounce_seconds: float = 5.0):
        self.buffers: Dict[str, Dict[str, Any]] = {}
        self.process_callback = process_callback
        self.debounce_seconds = debounce_seconds

    def add_message(self, key: str, message: str, metadata: Optional[Dict] = None):
        """
        Add a message to the buffer for the given key.
        Cancels existing timer and starts a new one (debounce).
        """
        if key in self.buffers:
            self.buffers[key]['task'].cancel()
            self.buffers[key]['messages'].append(message)
            # Update metadata if provided (merge or overwrite)
            if metadata:
                self.buffers[key]['metadata'].update(metadata)
        else:
            self.buffers[key] = {
                'messages': [message],
                'task': None,
                'metadata': metadata or {}
            }
        
        # Schedule processing
        task = asyncio.create_task(self._delayed_processing(key))
        self.buffers[key]['task'] = task

    async def _delayed_processing(self, key: str):
        await asyncio.sleep(self.debounce_seconds)
        try:
            # Prepare data to pass to callback
            if key in self.buffers:
                data = self.buffers.pop(key)
                messages = data['messages']
                metadata = data['metadata']
                combined_text = "\\n".join(messages)
                
                # Execute callback
                await self.process_callback(key, combined_text, metadata)
        except Exception as e:
            print(f"Error in message buffer processing for key {key}: {e}")
            import traceback
            traceback.print_exc()

class TimezoneUtils:
    """Helper utilities for timezone conversion and formatting."""
    
    @staticmethod
    def get_timezone(tz_str: Optional[str] = None) -> ZoneInfo:
        try:
            return ZoneInfo(tz_str) if tz_str else ZoneInfo('Asia/Kolkata')
        except Exception:
            return ZoneInfo('Asia/Kolkata')

    @staticmethod
    def format_timestamp(dt: datetime, tz_str: str = 'Asia/Kolkata') -> str:
        """Format datetime into a readable string with timezone."""
        target_tz = TimezoneUtils.get_timezone(tz_str)
        
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        
        local_dt = dt.astimezone(target_tz)
        
        day_name = local_dt.strftime("%A")
        day = local_dt.day
        month = local_dt.strftime("%b")
        year = local_dt.year
        
        if 10 <= day % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        
        date_str = f"{day_name}, {day}{suffix} {month} {year}"
        time_str = local_dt.strftime("%H:%M")
        
        return f"Date: {date_str}\\nTime: {time_str}\\nTimezone: {tz_str}"
