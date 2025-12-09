import os
import asyncio
import logging
from aiohttp import web
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.aiohttp import to_bolt_request, to_aiohttp_response
from slack_bolt.oauth.async_oauth_settings import AsyncOAuthSettings
from agent.agent import Agent
from user_manager import create_or_update_user, get_user
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from .store import CustomInstallationStore

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
        # Patch missing attributes required by AsyncApp
        bolt_req.method = request.method
        bolt_req.path = request.path
        bolt_req.query = dict(request.query)
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
            scopes=["app_mentions:read", "chat:write", "im:history", "users:read"], # Add other scopes as needed
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
        
        # Register handlers
        self.register_handlers()

    def register_handlers(self):
        """Register event handlers."""
        
        @self.app.event("message")
        async def handle_message_events(body, logger, client):
            event = body.get("event", {})
            
            # Ignore bot messages and message changes/deletions for now
            if event.get("bot_id") or event.get("subtype"):
                return
            
            user_id = event.get("user")
            text = event.get("text")
            channel = event.get("channel")
            channel_type = event.get("channel_type")
            ts = event.get("ts") # Timestamp
            team_id = body.get("team_id") # Get team_id from the outer body
            
            # Only process 1:1 Direct Messages
            if channel_type != "im":
                return
            
            if not user_id or not text:
                return

            # Get user info from Slack
            try:
                user_info = await client.users_info(user=user_id)
                user_data = user_info.get("user", {})
                
                real_name = user_data.get("real_name")
                display_name = user_data.get("profile", {}).get("display_name")
                username = display_name or user_data.get("name") # Fallback to name if display_name is empty
                
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
                    create_or_update_user(
                        telegram_id=user_id,
                        first_name=real_name,
                        username=username,
                        platform='slack',
                        team_id=team_id
                    )
                    
            except Exception as e:
                logger.error(f"Error fetching user info: {e}")
                # Continue anyway, maybe user exists
            
            # Extract text from attachments (forwarded messages)
            attachments = event.get("attachments", [])
            attachment_text = ""
            for attachment in attachments:
                # Get text, fallback to title or fallback field
                a_text = attachment.get("text") or attachment.get("title") or attachment.get("fallback")
                if a_text:
                    attachment_text += f"\n[Forwarded Message]: {a_text}"
            
            # Append attachment text to main text
            if attachment_text:
                text += attachment_text

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
            
            # Schedule processing
            async def delayed_processing():
                await asyncio.sleep(5) # 5 seconds debounce
                await self.process_buffered_messages(user_id, client)
            
            self.user_message_buffers[user_id]['task'] = asyncio.create_task(delayed_processing())

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
            message_timestamp_utc = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            IST = timezone(timedelta(hours=5, minutes=30))
            message_timestamp_ist = message_timestamp_utc.astimezone(IST)
            
            has_response = False
            
            async for chunk in self.agent.invoke(
                user_id,
                combined_text,
                "End-User via Slack",
                message_timestamp_ist
            ):
                if chunk.strip():
                    await client.chat_postMessage(channel=channel, text=chunk)
                    has_response = True
            
            if not has_response:
                await client.chat_postMessage(channel=channel, text="Sorry, I couldn't process that.")
                
        except Exception as e:
            print(f"Error processing Slack message: {e}")
            await client.chat_postMessage(channel=channel, text="Oops, something went wrong.")

        # Custom install handler
    async def handle_install(self, request):
        try:
            # Convert aiohttp request to Bolt request to ensure cookies/headers are processed for state
            bolt_req = await to_bolt_request(request)
            # Patch missing attributes for BoltRequest if needed (similar to handler)
            bolt_req.method = request.method
            bolt_req.path = request.path
            bolt_req.query = dict(request.query)

            # Generate state using the proper Bolt request
            state = await self.app.oauth_flow.issue_new_state(bolt_req)
            print(f"DEBUG: Generated OAuth State: {state}")
            
            # Generate the OAuth URL
            url = await self.app.oauth_flow.build_authorize_url(
                state=state,
                request=bolt_req
            )
            
            # Raise exception instead of returning it to avoid DeprecationWarning
            raise web.HTTPFound(url)
        except web.HTTPFound:
            raise
        except Exception as e:
            print(f"Error handling install redirect: {e}")
            return web.Response(status=500, text="Internal Server Error")

    # Custom OAuth callback handler
    async def handle_oauth_redirect(self, request):
        try:
            print(f"DEBUG: Callback Query: {dict(request.query)}")
            # Convert aiohttp request to Bolt request
            bolt_req = await to_bolt_request(request)
            # Patch missing attributes
            bolt_req.method = request.method
            bolt_req.path = request.path
            bolt_req.query = dict(request.query)
            
            # Handle the callback directly using the OAuth flow
            # This bypasses the global authorization middleware
            completion = await self.app.oauth_flow.handle_callback(bolt_req)
            
            return await to_aiohttp_response(completion)
        except Exception as e:
            print(f"Error handling OAuth redirect: {e}")
            return web.Response(status=500, text=f"Installation failed: {e}")

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
        
        # Bind routes to the AsyncSlackRequestHandler
        app.add_routes([
            web.post("/slack/events", self.handler.handle),
            web.get("/slack/install", self.handle_install), # Custom handler
            web.get("/slack/oauth_redirect", self.handle_oauth_redirect), # Custom handler
        ])

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 3000)
        await site.start()
        
        print("Slack HTTP Server running on port 3000.")
        
        # Keep running - looking for a way to keep this alive if it's the only thing, 
        # but in main.py this is awaited. 
        # Since site.start() is non-blocking, we need a keep-alive here or rely on the main loop.
        # Given main.py awaits this, we should return a future or just sleep forever.
        # However, main.py awaits both bots. main() ends if this returns.
        # site.start() starts the server in bg.
        
        # We'll just return control. main.py has `asyncio.run(main())` which finishes if tasks finish.
        # But wait, in main.py:
        # await telegram_bot.start() (returns, non-blocking updater)
        # await slack_bot.start() (WAS blocking with socket mode)
        # We need to make this blocking or main.py will exit.
        
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()
