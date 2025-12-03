import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import os
import sys

# Set environment variable before importing main
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock user_manager before importing main
with patch('user_manager.get_user') as mock_get_user, \
     patch('user_manager.create_or_update_user') as mock_create_user:
    from main import TelegramBot

# Save original sleep to use for yielding control in tests
original_sleep = asyncio.sleep

class TestDebouncing(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Mock Agent
        self.mock_agent_patcher = patch('main.Agent')
        self.mock_agent_class = self.mock_agent_patcher.start()
        self.mock_agent_instance = self.mock_agent_class.return_value
        # Mock invoke to return an empty async iterator
        async def async_iter(*args, **kwargs):
            yield "Response"
        self.mock_agent_instance.invoke.side_effect = async_iter

        # Mock user manager functions
        self.mock_get_user = patch('main.get_user').start()
        self.mock_get_user.return_value = {'name': 'Test', 'telegram_username': 'test', 'has_zarie': True}
        self.mock_create_user = patch('main.create_or_update_user').start()

        self.bot = TelegramBot()
        # Override agent with our mock instance directly to be sure
        self.bot.agent = self.mock_agent_instance

    async def asyncTearDown(self):
        self.mock_agent_patcher.stop()
        patch.stopall()

    async def test_debouncing_single_message(self):
        # Mock Update and Context
        update = MagicMock()
        update.effective_user.id = 12345
        update.message.text = "Hello"
        update.message.date = MagicMock()
        update.message.chat.send_action = AsyncMock()
        update.message.reply_text = AsyncMock()
        
        context = MagicMock()

        # Patch asyncio.sleep ONLY for the bot's execution context if possible, 
        # or just use original_sleep to yield.
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            # Call handle_message
            await self.bot.handle_message(update, context)
            
            # Yield control using REAL sleep to let the background task start
            await original_sleep(0.01)
            
            # Now the background task should have run, called mock_sleep, and continued.
            
            # Verify invoke called
            self.mock_agent_instance.invoke.assert_called_once()
            args = self.mock_agent_instance.invoke.call_args
            self.assertEqual(args[0][1], "Hello")

    async def test_debouncing_double_text(self):
        # Mock Update and Context
        update1 = MagicMock()
        update1.effective_user.id = 67890
        update1.message.text = "Hello"
        update1.message.date = MagicMock()
        update1.message.chat.send_action = AsyncMock()
        update1.message.reply_text = AsyncMock()

        update2 = MagicMock()
        update2.effective_user.id = 67890
        update2.message.text = "World"
        update2.message.date = MagicMock()
        update2.message.chat.send_action = AsyncMock()
        update2.message.reply_text = AsyncMock()
        
        context = MagicMock()

        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            # We need to control the sleep in the task.
            # Task 1 starts, calls sleep(4). We want it to hang there.
            # Task 2 starts, cancels Task 1, calls sleep(4). We want it to finish.
            
            # If mock_sleep returns immediately, Task 1 might finish before Task 2 starts 
            # if we yield control too long.
            
            # Strategy:
            # 1. Send msg 1.
            # 2. Send msg 2 immediately (don't yield in between).
            # 3. Yield.
            
            # If we don't yield between 1 and 2, Task 1 is scheduled but hasn't started.
            # Task 2 cancels Task 1 (which hasn't started).
            # Task 2 is scheduled.
            # Then we yield. Task 2 runs.
            
            await self.bot.handle_message(update1, context)
            await self.bot.handle_message(update2, context)
            
            # Yield to let tasks run
            await original_sleep(0.01)
            
            # Verify invoke called once
            self.mock_agent_instance.invoke.assert_called_once()
            args = self.mock_agent_instance.invoke.call_args
            self.assertEqual(args[0][1], "Hello\nWorld")

if __name__ == '__main__':
    unittest.main()
