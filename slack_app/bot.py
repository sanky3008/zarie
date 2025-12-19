import os
import asyncio
import logging
import re
from aiohttp import web
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.aiohttp import to_bolt_request, to_aiohttp_response
from slack_bolt.oauth.async_oauth_settings import AsyncOAuthSettings
from agent.agent import Agent
from user_manager import create_or_update_user, get_user
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from .store import CustomInstallationStore
from agent.state.mpim_state import (
    store_mpim_message, get_cached_slack_user, upsert_slack_user,
    build_mpim_context
)

load_dotenv()

# Shared agent instance
_agent = None

def get_agent():
    """Get or create the shared agent instance."""
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent

class AsyncSlackRequestHandler:
    def __init__(self, app):
        self.app = app

    async def handle(self, request):
        bolt_req = await to_bolt_request(request)
        resp = await self.app.async_dispatch(bolt_req)
        return await to_aiohttp_response(resp)
    
    async def handle_oauth(self, request):
        """Handle OAuth requests without signature verification."""
        bolt_req = await to_bolt_request(request)
        # OAuth requests go directly to the OAuth flow, bypassing signature verification
        if request.path == "/slack/install":
            resp = await self.app.oauth_flow.handle_installation(bolt_req)
        elif request.path == "/slack/oauth_redirect":
            resp = await self.app.oauth_flow.handle_callback(bolt_req)
        else:
            resp = await self.app.async_dispatch(bolt_req)
        return await to_aiohttp_response(resp)

class SlackBot:
    def __init__(self):
        """Initialize the Slack bot."""
        self.agent = get_agent()
        
        self.client_id = os.getenv("SLACK_CLIENT_ID")
        self.client_secret = os.getenv("SLACK_CLIENT_SECRET")
        self.signing_secret = os.getenv("SLACK_SIGNING_SECRET")
        
        if not self.client_id or not self.client_secret or not self.signing_secret:
            raise ValueError("SLACK_CLIENT_ID, SLACK_CLIENT_SECRET, and SLACK_SIGNING_SECRET must be set.")
        
        self.installation_store = CustomInstallationStore(client_id=self.client_id)
        
        oauth_settings = AsyncOAuthSettings(
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=["app_mentions:read", "chat:write", "im:history", "users:read", "mpim:history"],
            installation_store=self.installation_store,
            install_path="/slack/install",
            redirect_uri_path="/slack/oauth_redirect",
            install_page_rendering_enabled=False,
            state_validation_enabled=False
        )
        
        self.app = AsyncApp(
            signing_secret=self.signing_secret,
            oauth_settings=oauth_settings
        )
        
        self.handler = AsyncSlackRequestHandler(self.app)
        
        # Buffer for debouncing: { user_id: { 'messages': [str], 'task': asyncio.Task } }
        self.user_message_buffers = {}
        
        # MPIM message buffers: { channel_id: { 'messages': [...], 'task': asyncio.Task } }
        self.mpim_message_buffers = {}
        
        # Register handlers
        self.register_handlers()

    async def _get_user_display_name(self, client, user_id: str, team_id: str) -> str:
        """Get user display name with caching."""
        # Check cache first
        cached = get_cached_slack_user(user_id)
        if cached:
            return cached.get('display_name') or cached.get('real_name') or user_id
        
        # Fetch from Slack API
        try:
            user_info = await client.users_info(user=user_id)
            user_data = user_info.get("user", {})
            display_name = user_data.get("profile", {}).get("display_name")
            real_name = user_data.get("real_name")
            
            # Cache it
            upsert_slack_user(user_id, team_id, display_name, real_name)
            
            return display_name or real_name or user_id
        except Exception as e:
            print(f"Error fetching user info for {user_id}: {e}")
            return user_id

    def _is_bot_mentioned(self, event: dict, bot_user_id: str = None) -> bool:
        """Check if the bot is mentioned in the message."""
        text = event.get("text", "")
        # Check for @mention pattern
        # Slack mentions look like <@U1234567>
        if bot_user_id and f"<@{bot_user_id}>" in text:
            return True
        # Also check for "zarie" case-insensitive
        # REMOVED: strict tagging required for MPIM as per user request
        # if re.search(r'\bzarie\b', text, re.IGNORECASE):
        #    return True
        return False

    def _normalize_bot_mention(self, text: str, bot_user_id: str = None) -> str:
        """Replace bot mention with 'Zarie' for cleaner LLM input."""
        if bot_user_id:
            text = text.replace(f"<@{bot_user_id}>", "Zarie")
        # Also normalize "@zarie" or "zarie" to "Zarie"
        text = re.sub(r'@zarie', 'Zarie', text, flags=re.IGNORECASE)
        return text.strip()

    def register_handlers(self):
        """Register event handlers."""
        
        @self.app.event("message")
        async def handle_message_events(body, logger, client):
            event = body.get("event", {})
            
            # Ignore bot messages and message changes/deletions
            if event.get("bot_id") or event.get("subtype"):
                return
            
            user_id = event.get("user")
            text = event.get("text")
            channel = event.get("channel")
            channel_type = event.get("channel_type")
            ts = event.get("ts")
            thread_ts = event.get("thread_ts")  # None if root message
            team_id = body.get("team_id")
            
            if not user_id or not text:
                return
            
            # Route based on channel type
            if channel_type == "im":
                # DM - use existing logic
                await self._handle_dm_message(body, event, client, logger)
            
            elif channel_type in ["mpim", "group"]:
                # MPIM - new logic
                await self._handle_mpim_message(body, event, client, logger)
            
            # Ignore public/private channels (not supported)
            else:
                return

    async def _handle_dm_message(self, body, event, client, logger):
        """Handle 1:1 Direct Message (existing logic)."""
        user_id = event.get("user")
        text = event.get("text")
        channel = event.get("channel")
        ts = event.get("ts")
        team_id = body.get("team_id")
        
        # Get user info from Slack
        try:
            user_info = await client.users_info(user=user_id)
            user_data = user_info.get("user", {})
            
            real_name = user_data.get("real_name")
            display_name = user_data.get("profile", {}).get("display_name")
            username = display_name or user_data.get("name")
            
            # Check/Update user in DB
            existing_user = get_user(user_id)
            should_update = True
            
            if existing_user:
                if (existing_user.get('name') and 
                    existing_user.get('telegram_username') and 
                    existing_user.get('has_zarie') and
                    existing_user.get('platform') == 'slack' and
                    existing_user.get('team_id') == team_id):
                    should_update = False
            
            if should_update:
                tz = user_data.get("tz")
                create_or_update_user(
                    telegram_id=user_id,
                    first_name=real_name,
                    username=username,
                    platform='slack',
                    team_id=team_id,
                    timezone=tz
                )
                
        except Exception as e:
            logger.error(f"Error fetching user info: {e}")
        
        # Extract text from attachments
        attachments = event.get("attachments", [])
        for attachment in attachments:
            a_text = attachment.get("text") or attachment.get("title") or attachment.get("fallback")
            if a_text:
                text += f"\n[Forwarded Message]: {a_text}"

        # Debouncing logic
        if user_id in self.user_message_buffers:
            self.user_message_buffers[user_id]['task'].cancel()
            self.user_message_buffers[user_id]['messages'].append(text)
        else:
            self.user_message_buffers[user_id] = {
                'messages': [text],
                'task': None,
                'channel': channel,
                'ts': ts
            }
        
        async def delayed_processing():
            await asyncio.sleep(5)
            await self.process_buffered_messages(user_id, client)
        
        self.user_message_buffers[user_id]['task'] = asyncio.create_task(delayed_processing())

    async def _handle_mpim_message(self, body, event, client, logger):
        """Handle Multi-Party DM message."""
        author_id = event.get("user")
        text = event.get("text")
        channel_id = event.get("channel")
        ts = event.get("ts")
        thread_ts = event.get("thread_ts")  # None if root message
        team_id = body.get("team_id")
        
        # Get bot user ID to check mentions
        bot_user_id = None
        try:
            auth_result = await client.auth_test()
            bot_user_id = auth_result.get("user_id")
        except Exception as e:
            logger.error(f"Error getting bot user ID: {e}")
        
        # Get author display name (with caching)
        author_name = await self._get_user_display_name(client, author_id, team_id)
        
        # Ensure MPIM pseudo-user exists in DB
        existing_mpim = get_user(channel_id)
        if not existing_mpim:
            # Create MPIM as pseudo-user
            create_or_update_user(
                telegram_id=channel_id,
                first_name=f"MPIM-{channel_id[:8]}",
                username=None,
                platform='slack',
                team_id=team_id,
                timezone='UTC'  # Will be overridden by first user's timezone
            )
            # Update user_type to 'mpim'
            from user_manager import get_db_connection
            conn, db_type = get_db_connection()
            cursor = conn.cursor()
            try:
                if db_type == 'postgres':
                    cursor.execute("UPDATE users SET user_type = 'mpim' WHERE telegram_id = %s", (channel_id,))
                else:
                    cursor.execute("UPDATE users SET user_type = 'mpim' WHERE telegram_id = ?", (channel_id,))
                conn.commit()
            finally:
                conn.close()
        
        # Extract text from attachments
        attachments = event.get("attachments", [])
        for attachment in attachments:
            a_text = attachment.get("text") or attachment.get("title") or attachment.get("fallback")
            if a_text:
                text += f"\n[Forwarded Message]: {a_text}"
        
        # Normalize text and strip bot mention BEFORE storing
        clean_text = self._normalize_bot_mention(text, bot_user_id)
        
        # --- NEW: Format message before storing (bake in metadata) ---
        from zoneinfo import ZoneInfo
        
        # Get author's timezone
        author_user = get_user(author_id)
        author_tz_str = author_user.get('timezone', 'Asia/Kolkata') if author_user else 'Asia/Kolkata'
        try:
            author_tz = ZoneInfo(author_tz_str)
        except:
            author_tz = ZoneInfo('Asia/Kolkata')
            author_tz_str = 'Asia/Kolkata'
            
        # Create timestamp
        msg_ts = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        local_dt = msg_ts.astimezone(author_tz)
        
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
        
        # Format: Date/Time headers + FROM header + Message
        formatted_content = f"Date: {date_str}\nTime: {time_str}\nTimezone: {author_tz_str}\nFROM: End-User via Slack MPIM\nAuthor: {author_name} | <@{author_id}>\nMessage: {clean_text}"
        
        # Store message in chats_context (always, even if not mentioning bot)
        store_mpim_message(
            user_id=channel_id,
            role="user",
            content=formatted_content, # Store FORMATTED content
            author_id=author_id,
            author_name=author_name,
            thread_ts=thread_ts,
            slack_ts=ts
        )
        
        # Only invoke Zarie if mentioned
        if not self._is_bot_mentioned(event, bot_user_id):
            return
        
        # Use debouncing for MPIM too (with channel+thread as key)
        buffer_key = f"{channel_id}:{thread_ts or ts}"
        
        if buffer_key in self.mpim_message_buffers:
            self.mpim_message_buffers[buffer_key]['task'].cancel()
            self.mpim_message_buffers[buffer_key]['messages'].append(clean_text) # Still buffer raw text for LLM invocation? 
            # WAIT: Agent invocation also bakes it in usually?
            # Actually Agent.invoke takes 'message' as raw text.
            # But Agent._current_is_mpim is True.
            # The agent.py logic for MPIM context building USES stored messages.
            # So if we store formatted, we must ensure the `mpim_state` handles it.
            # AND the `invoke` call should probably still take raw text or handle it.
            # Let's keep buffering `clean_text` for the immediate turn invocation
            # because `invoke` takes raw text in `combined_text`.
        else:
            self.mpim_message_buffers[buffer_key] = {
                'messages': [clean_text],
                'task': None,
                'channel': channel_id,
                'ts': ts,
                'thread_ts': thread_ts,
                'team_id': team_id,
                'author_name': author_name
            }
        
        async def delayed_mpim_processing():
            await asyncio.sleep(5)
            await self._process_mpim_messages(buffer_key, client)
        
        self.mpim_message_buffers[buffer_key]['task'] = asyncio.create_task(delayed_mpim_processing())

    async def _process_mpim_messages(self, buffer_key: str, client):
        """Process buffered MPIM messages and invoke Zarie."""
        if buffer_key not in self.mpim_message_buffers:
            return
        
        buffer_data = self.mpim_message_buffers.pop(buffer_key)
        messages = buffer_data['messages']
        channel_id = buffer_data['channel']
        ts = buffer_data['ts']
        thread_ts = buffer_data['thread_ts']
        team_id = buffer_data['team_id']
        author_name = buffer_data['author_name']
        
        if not messages:
            return
        
        combined_text = "\n".join(messages)
        
        # The thread to reply to: if original was in a thread, use that thread_ts
        # If original was root message, reply to that message (creating a new thread)
        reply_thread_ts = thread_ts or ts
        
        try:
            message_timestamp_utc = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            
            # Get user timezone (use first participant's or default)
            mpim_user = get_user(channel_id)
            user_timezone = mpim_user.get('timezone', 'Asia/Kolkata') if mpim_user else 'Asia/Kolkata'
            
            has_response = False
            
            async for chunk in self.agent.invoke(
                channel_id,
                combined_text,
                "End-User via Slack MPIM",
                message_timestamp_utc,
                user_timezone,
                is_mpim=True,
                thread_ts=thread_ts, # Pass original thread_ts (None for root) for context lookup
                author_name=author_name,
                reply_ts=reply_thread_ts # Pass the reply thread ID to tools
            ):
                if chunk.strip():
                    if "No_Response_Needed" in chunk:
                        has_response = True
                        continue
                    # Always reply in thread for MPIM
                    await client.chat_postMessage(
                        channel=channel_id, 
                        text=chunk,
                        thread_ts=reply_thread_ts
                    )
                    has_response = True
            
            if not has_response:
                pass
                
        except Exception as e:
            print(f"Error processing MPIM message: {e}")
            import traceback
            traceback.print_exc()
            await client.chat_postMessage(
                channel=channel_id, 
                text="Oops, something went wrong.",
                thread_ts=reply_thread_ts
            )

    async def process_buffered_messages(self, user_id, client):
        """Process buffered messages for a user."""
        if user_id not in self.user_message_buffers:
            return
            
        buffer_data = self.user_message_buffers.pop(user_id)
        messages = buffer_data['messages']
        channel = buffer_data['channel']
        ts = buffer_data['ts']
        
        if not messages:
            return
            
        combined_text = "\n".join(messages)
        
        try:
            # Calculate timestamp
            # Calculate timestamp
            message_timestamp_utc = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            
            # Fetch user for timezone
            user = get_user(user_id)
            user_timezone = user.get('timezone', 'Asia/Kolkata') if user else 'Asia/Kolkata'
            
            has_response = False
            
            async for chunk in self.agent.invoke(
                user_id,
                combined_text,
                "End-User via Slack",
                message_timestamp_utc,
                user_timezone
            ):
                if chunk.strip():
                    if "No_Response_Needed" in chunk:
                        has_response = True
                        continue
                    await client.chat_postMessage(channel=channel, text=chunk)
                    has_response = True
            
            if not has_response:
                await client.chat_postMessage(channel=channel, text="Sorry, I couldn't process that.")
                
        except Exception as e:
            print(f"Error processing Slack message: {e}")
            await client.chat_postMessage(channel=channel, text="Oops, something went wrong.")

    async def start(self):
        """Start the Slack bot (HTTP Server for Events + OAuth)."""
        print("Starting Slack HTTP Server on port 3000...")

        app = web.Application()
        
        # Simple logging middleware
        @web.middleware
        async def logging_middleware(request, handler):
            print(f"Request received: {request.method} {request.path}")
            return await handler(request)
            
        app.middlewares.append(logging_middleware)
        
        # Route endpoints:
        # - POST /slack/events → Event handling (with signature verification)
        # - GET /slack/install → OAuth authorization (no signature)
        # - GET /slack/oauth_redirect → OAuth callback (no signature)
        app.router.add_post("/slack/events", self.handler.handle)
        app.router.add_get("/slack/install", self.handler.handle_oauth)
        app.router.add_get("/slack/oauth_redirect", self.handler.handle_oauth)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 3000)
        await site.start()
        
        print("Slack HTTP Server running on port 3000.")
        print("Endpoints configured:")
        print("  - POST /slack/events (Event API)")
        print("  - GET /slack/install (OAuth authorization)")
        print("  - GET /slack/oauth_redirect (OAuth callback)")
        
        # Keep the server running
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()
