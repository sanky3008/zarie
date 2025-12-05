import os
import asyncio
import logging
from aiohttp import web
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
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

class SlackBot:
    def __init__(self):
        """Initialize the Slack bot."""
        self.agent = get_agent()
        
        self.app_token = os.getenv("SLACK_APP_TOKEN")
        self.client_id = os.getenv("SLACK_CLIENT_ID")
        self.client_secret = os.getenv("SLACK_CLIENT_SECRET")
        self.signing_secret = os.getenv("SLACK_SIGNING_SECRET")
        
        if not self.app_token or not self.client_id or not self.client_secret or not self.signing_secret:
            raise ValueError("SLACK_APP_TOKEN, SLACK_CLIENT_ID, SLACK_CLIENT_SECRET, and SLACK_SIGNING_SECRET must be set.")
        
        self.installation_store = CustomInstallationStore(client_id=self.client_id)
        
        oauth_settings = AsyncOAuthSettings(
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=["app_mentions:read", "chat:write", "im:history", "im:write", "users:read"], # Add other scopes as needed
            installation_store=self.installation_store,
            install_path="/slack/install",
            redirect_uri_path="/slack/oauth_redirect",
        )
        
        self.app = AsyncApp(
            signing_secret=self.signing_secret,
            oauth_settings=oauth_settings
        )
        
        self.handler = AsyncSocketModeHandler(self.app, self.app_token)
        
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
            ts = event.get("ts") # Timestamp
            team_id = body.get("team_id") # Get team_id from the outer body
            
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

    async def start(self):
        """Start the Slack bot (Socket Mode + OAuth Server)."""
        print("Starting Slack Socket Mode Handler...")
        # Start Socket Mode in the background
        socket_task = asyncio.create_task(self.handler.start_async())
        
        print("Starting Slack OAuth Server on port 3000...")
        # Start the web server for OAuth manually to avoid blocking the loop
        # self.app.web_app is a method that returns the underlying aiohttp.web.Application
        runner = web.AppRunner(self.app.web_app())
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 3000)
        await site.start()
        
        print("Slack OAuth Server running on port 3000.")
        
        # Keep running until cancelled
        try:
            await socket_task
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()
