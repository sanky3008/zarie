import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from agent.agent import Agent
from user_manager import create_or_update_user, get_user
from dotenv import load_dotenv
from datetime import datetime, timezone
from agent.utils import MessageBuffer

load_dotenv()

# Shared agent instance for all handlers
_agent = None

# Blocked user IDs
BLOCKED_USER_IDS = set(id.strip() for id in os.getenv("BLOCKED_TELEGRAM_IDS", "").split(",") if id.strip())

# Whitelist: Only these user IDs will receive replies
ALLOWED_USER_IDS = {"7580670088", "868383156"}

def get_agent():
    """Get or create the shared agent instance."""
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent

class TelegramBot:
    def __init__(self):
        """Initialize the Telegram bot with the Agent."""
        self.agent = get_agent()
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not found in environment variables")
        
        # Use shared MessageBuffer
        self.message_buffer = MessageBuffer(self.process_buffered_messages)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /start command."""
        await update.message.reply_text(
            "Hi! I'm Zarie, your AI assistant. Send me a message and I'll help you out!"
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /help command."""
        await update.message.reply_text(
            "Just send me any message and I'll respond. That's all you need to know, boss."
        )
    
    async def process_buffered_messages(self, user_id: str, combined_text: str, metadata: dict):
        """Callback to process buffered messages."""
        update = metadata['update']
        
        # Send typing action to show the bot is working
        await update.message.chat.send_action(action="typing")
        
        try:
            # Get the message timestamp (already UTC in Telegram)
            message_timestamp_utc = update.message.date
            
            # Fetch user for timezone
            user = get_user(user_id)
            user_timezone = user.get('timezone', 'Asia/Kolkata') if user else 'Asia/Kolkata'
            
            # Stream response chunks from agent
            has_response = False
            async for chunk in self.agent.invoke(
                user_id, 
                combined_text, 
                "End-User via Telegram",
                message_timestamp_utc,
                user_timezone
            ):
                # Send each chunk as a separate message
                if chunk.strip():
                    # Robust check for No_Response_Needed token
                    normalized_chunk = chunk.lower().replace("_", "").replace(" ", "").replace("\\", "").replace("*", "").replace("`", "")
                    if "noresponseneeded" in normalized_chunk:
                        has_response = True
                        continue
                    await update.message.reply_text(chunk)
                    has_response = True
            
            # If no response was generated, notify user
            if not has_response:
                await update.message.reply_text("Sorry, I couldn't process that. Try again?")
        
        except Exception as e:
            print(f"Error processing message: {e}")
            import traceback
            traceback.print_exc()
            await update.message.reply_text(
                "Oops, something went wrong on my end. Give me a moment and try again."
            )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages with debouncing."""
        # Get user information
        user = update.effective_user
        user_id = str(user.id)  # Using Telegram user ID as the identifier
        
        # Check if user is blocked
        if user_id in BLOCKED_USER_IDS:
            print(f"Blocked message from user {user_id}")
            return
        
        # WHITELIST CHECK: Only allow specific user IDs
        if user_id not in ALLOWED_USER_IDS:
            print(f"Message from non-whitelisted user {user_id} - ignoring")
            return
        
        # Check/Update user
        await self._ensure_user_updated(user, user_id)
        
        message_text = update.message.text
        
        if len(message_text) > 100000:
            await update.message.reply_text("Message too long. Please keep it under 4000 characters.")
            return

        # Add to buffer
        metadata = {
            'update': update,
            'context': context
        }
        self.message_buffer.add_message(user_id, message_text, metadata)
    
    async def _ensure_user_updated(self, user, user_id):
        """Ensure user is updated in the database."""
        existing_user = get_user(user_id)
        
        should_update = True
        if existing_user:
            if (existing_user.get('name') and 
                existing_user.get('telegram_username') and 
                existing_user.get('has_zarie')):
                should_update = False
        
        if should_update:
            create_or_update_user(
                telegram_id=user_id,
                first_name=user.first_name,
                last_name=user.last_name,
                username=user.username
            )

    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle when a user shares their contact (optional feature)."""
        contact = update.message.contact
        if contact and contact.phone_number:
            await update.message.reply_text(
                f"Thanks for sharing your contact! I've noted your number: {contact.phone_number}"
            )
    
    def register_handlers(self, app):
        """Register all command and message handlers."""
        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        app.add_handler(MessageHandler(filters.CONTACT, self.handle_contact))

    async def start(self):
        """Start the Telegram bot in async mode (non-blocking)."""
        app = Application.builder().token(self.token).concurrent_updates(True).connect_timeout(30.0).read_timeout(30.0).write_timeout(30.0).build()
        self.register_handlers(app)
        
        await app.initialize()
        await app.start()
        
        webhook_url = os.getenv("WEBHOOK_URL")
        port = int(os.getenv("PORT", "8443"))
        
        if webhook_url:
            print(f"Starting Telegram webhook on port {port}")
            url_path = self.token.split(':')[-1]
            await app.bot.set_webhook(url=f"{webhook_url}/{url_path}")
            print("Warning: Webhook support in combined run.py requires a shared web server. Defaulting to polling logic for now if not using run_webhook.")
        
        print("Starting Telegram polling...")
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        return app

    def run(self):
        """Start the Telegram bot (blocking)."""
        app = Application.builder().token(self.token).concurrent_updates(True).connect_timeout(30.0).read_timeout(30.0).write_timeout(30.0).build()
        self.register_handlers(app)
        
        print("Telegram bot is running...")
        print("Press Ctrl+C to stop")
        
        webhook_url = os.getenv("WEBHOOK_URL")
        port = int(os.getenv("PORT", "8443"))

        if webhook_url:
            print(f"Starting webhook on port {port}")
            url_path = self.token.split(':')[-1]
            app.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=url_path,
                webhook_url=f"{webhook_url}/{url_path}"
            )
        else:
            print("Starting polling...")
            app.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    """Main function to start the Telegram bot."""
    bot = TelegramBot()
    bot.run()

if __name__ == "__main__":
    main()

