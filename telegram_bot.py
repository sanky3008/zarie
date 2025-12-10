import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from agent.agent import Agent
from user_manager import create_or_update_user, get_user
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

load_dotenv()

# Shared agent instance for all handlers
_agent = None

# Blocked user IDs
BLOCKED_USER_IDS = set(id.strip() for id in os.getenv("BLOCKED_TELEGRAM_IDS", "").split(",") if id.strip())

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
        
        # Dictionary to store buffered messages and timer tasks for each user
        # Format: { user_id: { 'messages': [str], 'task': asyncio.Task } }
        self.user_message_buffers = {}
    
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
    
    async def process_buffered_messages(self, user_id: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process buffered messages for a user after the debounce delay."""
        if user_id not in self.user_message_buffers:
            return

        # Retrieve and clear the buffer
        buffer_data = self.user_message_buffers.pop(user_id)
        messages = buffer_data['messages']
        
        if not messages:
            return

        # Combine messages
        combined_message_text = "\n".join(messages)
        
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
                combined_message_text, 
                "End-User via Telegram",
                message_timestamp_utc,
                user_timezone
            ):
                # Send each chunk as a separate message
                if chunk.strip():
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
        
        # Check if user exists and has necessary info
        existing_user = get_user(user_id)
        
        should_update = True
        if existing_user:
            # If user exists, has name, username, and has_zarie is True, we don't need to update
            if (existing_user.get('name') and 
                existing_user.get('telegram_username') and 
                existing_user.get('has_zarie')):
                should_update = False
        
        if should_update:
            # Save or update user in database
            create_or_update_user(
                telegram_id=user_id,
                first_name=user.first_name,
                last_name=user.last_name,
                username=user.username
            )
        
        message_text = update.message.text
        
        if len(message_text) > 100000:
            await update.message.reply_text("Message too long. Please keep it under 4000 characters.")
            return

        # Debouncing logic
        if user_id in self.user_message_buffers:
            # Cancel existing task
            self.user_message_buffers[user_id]['task'].cancel()
            # Append message to existing buffer
            self.user_message_buffers[user_id]['messages'].append(message_text)
        else:
            # Initialize new buffer
            self.user_message_buffers[user_id] = {
                'messages': [message_text],
                'task': None
            }
        
        # Define the delayed processing task
        async def delayed_processing():
            await asyncio.sleep(5)  # Wait for 5 seconds
            await self.process_buffered_messages(user_id, update, context)

        # Schedule the new task
        self.user_message_buffers[user_id]['task'] = asyncio.create_task(delayed_processing())
    
    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle when a user shares their contact (optional feature)."""
        contact = update.message.contact
        if contact and contact.phone_number:
            # Store phone number mapping if needed
            # For now, just acknowledge
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
        app = Application.builder().token(self.token).concurrent_updates(True).build()
        self.register_handlers(app)
        
        await app.initialize()
        await app.start()
        
        webhook_url = os.getenv("WEBHOOK_URL")
        port = int(os.getenv("PORT", "8443"))
        
        if webhook_url:
            print(f"Starting Telegram webhook on port {port}")
            url_path = self.token.split(':')[-1]
            await app.bot.set_webhook(url=f"{webhook_url}/{url_path}")
            # Note: For webhooks to work in this custom async flow, you'd typically need 
            # to attach this to a web server (like aiohttp or fastapi). 
            # For now, we'll assume polling for the combined run script or basic webhook setup.
            # If using run_webhook in run(), it blocks.
            # For this integration, we'll focus on Polling as it's easier to combine with Slack Socket Mode.
            print("Warning: Webhook support in combined run.py requires a shared web server. Defaulting to polling logic for now if not using run_webhook.")
        
        print("Starting Telegram polling...")
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        # Keep the application running
        # In a combined script, the main loop will keep this alive.
        return app

    def run(self):
        """Start the Telegram bot (blocking)."""
        # Create the Application with concurrent updates enabled
        app = Application.builder().token(self.token).concurrent_updates(True).build()
        self.register_handlers(app)
        
        print("Telegram bot is running...")
        print("Press Ctrl+C to stop")
        
        # Start the bot
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

