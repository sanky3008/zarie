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
from datetime import datetime, timezone
from .store import CustomInstallationStore
from agent.utils import MessageBuffer

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
        
        # Shared Buffer for both DM and MPIM
        # Key: user_id (for DM) OR "channel_id:thread_ts" (for MPIM)
        self.message_buffer = MessageBuffer(self.process_buffered_messages)
        
        # Register handlers
        self.register_handlers()

    async def _get_user_display_name(self, client, user_id: str, team_id: str) -> str:
        """Get user display name with caching."""
        # Use State's user cache
        cached = self.agent.state.get_cached_slack_user(user_id)
        if cached:
            return cached.get('display_name') or cached.get('real_name') or user_id
        
        # Fetch from Slack API
        try:
            user_info = await client.users_info(user=user_id)
            user_data = user_info.get("user", {})
            display_name = user_data.get("profile", {}).get("display_name")
            real_name = user_data.get("real_name")
            timezone = user_data.get("tz")
            
            # Cache it
            self.agent.state.upsert_slack_user(user_id, team_id, display_name, real_name, timezone)
            
            return display_name or real_name or user_id
        except Exception as e:
            print(f"Error fetching user info for {user_id}: {e}")
            return user_id

    def _is_bot_mentioned(self, event: dict, bot_user_id: str = None) -> bool:
        """Check if the bot is mentioned in the message."""
        text = event.get("text", "")
        # Check for @mention pattern <@U1234567>
        if bot_user_id and f"<@{bot_user_id}>" in text:
            return True
        return False

    def _normalize_bot_mention(self, text: str, bot_user_id: str = None) -> str:
        """Replace bot mention with 'Zarie' for cleaner LLM input."""
        if bot_user_id:
            text = text.replace(f"<@{bot_user_id}>", "Zarie")
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
            channel_id = event.get("channel")
            channel_type = event.get("channel_type")
            ts = event.get("ts")
            thread_ts = event.get("thread_ts")
            team_id = body.get("team_id")
            
            if not user_id or not text:
                return
            
            # Route based on channel type
            if channel_type == "im":
                await self._handle_dm_message(body, event, client, logger)
            
            elif channel_type in ["mpim", "group"]:
                await self._handle_mpim_message(body, event, client, logger)

        @self.app.event("app_home_opened")
        async def handle_app_home_opened(body, client, logger):
            """Send welcome message when user first opens Messages tab."""
            event = body.get("event", {})
            user_id = event.get("user")

            # Only send welcome if it's the Messages tab
            if event.get("tab") == "messages":
                try:
                    await client.chat_postMessage(
                        channel=user_id,
                        text="👋 Hey! I'm Zarie, your AI personal assistant.\n\n"
                             "I can help you with:\n"
                             "• Managing your calendar and avoiding scheduling conflicts\n"
                             "• Checking your emails and sending summaries\n"
                             "• Setting reminders and recurring tasks\n"
                             "• Automating workflows\n\n"
                             "Just message me naturally - ask me anything!\n\n"
                             "Need support or have feedback? Email sanky@zarie.chat"
                    )
                except Exception as e:
                    logger.error(f"Error sending welcome message: {e}")

    async def _handle_dm_message(self, body, event, client, logger):
        """Handle 1:1 Direct Message."""
        user_id = event.get("user")
        text = event.get("text")
        channel = event.get("channel")
        ts = event.get("ts")
        team_id = body.get("team_id")
        
        # Update user info if needed
        await self._ensure_user_updated(client, user_id, team_id)
        
        # Extract attachment text
        text = self._extract_text(event, text)
        
        # Buffer message
        metadata = {
            'channel': channel,
            'ts': ts,
            'client': client, # Pass client for callback
            'medium': "End-User via Slack",
            'is_mpim': False
        }
        self.message_buffer.add_message(user_id, text, metadata)

    async def _handle_mpim_message(self, body, event, client, logger):
        """Handle Multi-Party DM message."""
        author_id = event.get("user")
        text = event.get("text")
        channel_id = event.get("channel")
        ts = event.get("ts")
        thread_ts = event.get("thread_ts")
        team_id = body.get("team_id")
        
        # Get bot user ID to check mentions
        bot_user_id = (await client.auth_test()).get("user_id")
        
        # Get author display name
        author_name = await self._get_user_display_name(client, author_id, team_id)
        
        # Ensure MPIM pseudo-user exists
        self._ensure_mpim_user(channel_id, team_id)
        
        # Extract attachment text
        text = self._extract_text(event, text)
        clean_text = self._normalize_bot_mention(text, bot_user_id)
        
        # Check strict mention requirement for MPIM invocation
        is_mentioned = self._is_bot_mentioned(event, bot_user_id)
        
        # Ensure author info is updated (especially FIRST message from user)
        # This fixes timezone issues by caching the user's timezone from Slack
        await self._ensure_user_updated(client, author_id, team_id)
        
        # Even if not mentioned, we might want to store context?
        # But Agent.invoke handles storage. If we don't invoke, we don't store.
        # Wait, previous logic stored EVERYTHING using store_mpim_message manually.
        # To maintain that behavior (Agent sees history even if not pinged), we should
        # use a "store_only" flag or just rely on the fact that we ONLY invoke if mentioned.
        # BUT: For the agent to have context when it IS mentioned, it needs the history.
        # So we must store every message.
        
        # Store message asynchronously without invoking agent if not mentioned
        if not is_mentioned:
             # Manually store via Agent's state (using internal method or expose one? Agent.invoke stores it too)
             # Let's use a lightweight manual store since we don't want to trigger the LLM.
             timestamp = datetime.fromtimestamp(float(ts), tz=timezone.utc)
             # Get user timezone safely
             try:
                 user_tz = get_user(channel_id).get('timezone', 'Asia/Kolkata')
             except:
                 user_tz = 'Asia/Kolkata'

             # Create formatted message
             user_message = self.agent._create_user_message(
                 clean_text, "End-User via Slack MPIM", timestamp, user_tz, author_name, author_id
             )
             self.agent.state.add_context(
                 channel_id, user_message, thread_ts=thread_ts, author_name=author_name, author_id=author_id, slack_ts=ts
             )
             return

        # If mentioned, buffer and invoke
        key = f"{channel_id}:{thread_ts or ts}" # Unique key per thread
        metadata = {
            'channel': channel_id,
            'ts': ts,
            'thread_ts': thread_ts,
            'client': client,
            'medium': "End-User via Slack MPIM",
            'is_mpim': True,
            'author_name': author_name,
            'author_id': author_id,
            'team_id': team_id
        }
        self.message_buffer.add_message(key, clean_text, metadata)

    async def process_buffered_messages(self, key: str, combined_text: str, metadata: dict):
        """Callback to process buffered messages."""
        client = metadata['client']
        channel = metadata['channel']
        ts = metadata['ts']
        thread_ts = metadata.get('thread_ts')
        is_mpim = metadata.get('is_mpim', False)
        author_name = metadata.get('author_name')
        author_id = metadata.get('author_id')
        
        try:
            message_timestamp_utc = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            
            # Fetch user for timezone
            # Fetch user for timezone
            if is_mpim:
                user_id = channel # Use channel ID as user_id for context
                # For MPIM, use the AUTHOR's timezone (sender), not the channel's
                cached_user = self.agent.state.get_cached_slack_user(author_id)
                if cached_user and cached_user.get('timezone'):
                     user_timezone = cached_user.get('timezone')
                else:
                     user_timezone = 'Asia/Kolkata' # Default fallback
            else:
                # DM Case: key is user_id
                user_id = key 
                user = get_user(user_id)
                user_timezone = user.get('timezone', 'Asia/Kolkata') if user else 'Asia/Kolkata'
            
            reply_thread_ts = thread_ts or ts if is_mpim else None
            
            has_response = False
            
            async for chunk in self.agent.invoke(
                user_id=user_id,
                message=combined_text,
                medium=metadata['medium'],
                timestamp=message_timestamp_utc,
                user_timezone=user_timezone,
                is_mpim=is_mpim,
                thread_ts=thread_ts,
                author_name=author_name,
                author_id=author_id,
                reply_ts=reply_thread_ts
            ):
                if chunk.strip():
                    if "No_Response_Needed" in chunk:
                        has_response = True
                        continue
                    
                    # Send response
                    await client.chat_postMessage(
                        channel=channel, 
                        text=chunk,
                        thread_ts=reply_thread_ts # None for DM, active thread for MPIM
                    )
                    has_response = True
            
            if not has_response:
                # Optionally handle no response
                pass
                
        except Exception as e:
            print(f"Error processing Slack message: {e}")
            await client.chat_postMessage(channel=channel, text="Oops, something went wrong.", thread_ts=reply_thread_ts if is_mpim else None)

    async def _ensure_user_updated(self, client, user_id, team_id):
        """Helper to check/update user in DB."""
        try:
            existing_user = get_user(user_id)
            if existing_user and existing_user.get('platform') == 'slack':
                 return
            
            user_info = await client.users_info(user=user_id)
            user_data = user_info.get("user", {})
            create_or_update_user(
                telegram_id=user_id,
                first_name=user_data.get("real_name"),
                username=user_data.get("name"),
                platform='slack',
                team_id=team_id,
                timezone=user_data.get("tz")
            )
        except Exception:
            pass

    def _ensure_mpim_user(self, channel_id, team_id):
        """Helper to ensure MPIM pseudo-user exists."""
        if not get_user(channel_id):
            create_or_update_user(
                telegram_id=channel_id,
                first_name=f"MPIM-{channel_id[:8]}",
                username=None,
                platform='slack',
                team_id=team_id,
                timezone='UTC'
            )
            # Update type
            from user_manager import get_db_connection
            conn, db_type = get_db_connection()
            try:
                cursor = conn.cursor()
                query = "UPDATE users SET user_type = 'mpim' WHERE telegram_id = %s" if db_type == 'postgres' else "UPDATE users SET user_type = 'mpim' WHERE telegram_id = ?"
                cursor.execute(query, (channel_id,))
                conn.commit()
            finally:
                conn.close()

    def _extract_text(self, event, text):
        """Extract text from attachments if needed."""
        attachments = event.get("attachments", [])
        for attachment in attachments:
            a_text = attachment.get("text") or attachment.get("title") or attachment.get("fallback")
            if a_text:
                text += f"\n[Forwarded Message]: {a_text}"
        return text

    async def start(self):
        """Start the Slack bot (HTTP Server for Events + OAuth)."""
        print("Starting Slack HTTP Server on port 3000...")
        
        # Import Google OAuth handlers
        from oauth_server import handle_login, handle_oauth_callback
        
        app = web.Application()
        app.router.add_post("/slack/events", self.handler.handle)
        app.router.add_get("/slack/install", self.handler.handle_oauth)
        app.router.add_get("/slack/oauth_redirect", self.handler.handle_oauth)
        
        # Add Google OAuth routes
        app.router.add_get("/google/login", handle_login)
        app.router.add_get("/google/callback", handle_oauth_callback)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 3000)
        await site.start()
        
        print("Slack HTTP Server running on port 3000.")
        
        # Keep the server running
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()
