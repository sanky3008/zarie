import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from agent.agent import Agent
from user_manager import create_or_update_user
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

load_dotenv()

# Shared agent instance for all handlers
_agent = None

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
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages."""
        # Get user information
        user = update.effective_user
        user_id = str(user.id)  # Using Telegram user ID as the identifier
        
        # Save or update user in database
        create_or_update_user(
            telegram_id=user_id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username
        )
        
        # Note: To get phone number, the user must share their contact explicitly.
        # You can add a feature to request contact if needed.
        # For now, we'll use Telegram user ID as the unique identifier.
        
        message_text = update.message.text
        
        if len(message_text) > 10000:
            await update.message.reply_text("Message too long. Please keep it under 4000 characters.")
            return
        
        # Send typing action to show the bot is working
        await update.message.chat.send_action(action="typing")
        
        try:
            # Get the message timestamp and convert from UTC to IST
            message_timestamp_utc = update.message.date
            IST = timezone(timedelta(hours=5, minutes=30))
            message_timestamp_ist = message_timestamp_utc.astimezone(IST)
            
            # Stream response chunks from agent
            has_response = False
            async for chunk in self.agent.invoke(
                user_id, 
                message_text, 
                "End-User via Telegram",
                message_timestamp_ist
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
    
    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle when a user shares their contact (optional feature)."""
        contact = update.message.contact
        if contact and contact.phone_number:
            # Store phone number mapping if needed
            # For now, just acknowledge
            await update.message.reply_text(
                f"Thanks for sharing your contact! I've noted your number: {contact.phone_number}"
            )
    
    def run(self):
        """Start the Telegram bot."""
        # Create the Application with concurrent updates enabled
        app = Application.builder().token(self.token).concurrent_updates(True).build()
        
        # Register command handlers
        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("help", self.help_command))
        
        # Register message handler for text messages
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Optional: Register handler for contact sharing
        app.add_handler(MessageHandler(filters.CONTACT, self.handle_contact))
        
        print("Telegram bot is running...")
        print("Press Ctrl+C to stop")
        
        # Start the bot
        # Use webhooks in production, otherwise poll
        webhook_url = os.getenv("WEBHOOK_URL")
        port = int(os.getenv("PORT", "8443"))

        if webhook_url:
            # Production mode with webhooks
            print(f"Starting webhook on port {port}")
            # The URL path is often set to the bot token for simple security
            url_path = self.token.split(':')[-1]
            app.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=url_path,
                webhook_url=f"{webhook_url}/{url_path}"
            )
        else:
            # Development mode with polling
            print("Starting polling...")
            app.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Main function to start the Telegram bot."""
    bot = TelegramBot()
    bot.run()


if __name__ == "__main__":
    main()

