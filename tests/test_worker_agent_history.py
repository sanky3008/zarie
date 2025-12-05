import unittest
from unittest.mock import MagicMock, patch
import json
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker_agent.agent.agent import WorkerAgent

class TestWorkerAgentHistory(unittest.TestCase):
    def setUp(self):
        self.agent = WorkerAgent(db_path=":memory:")
        self.agent.directory = MagicMock()
        
    @patch('worker_agent.agent.agent.get_system_prompt')
    def test_prepare_messages_filtering(self, mock_get_system_prompt):
        mock_get_system_prompt.return_value = "System Prompt"
        
        # Create a history with 10 user messages interleaved with assistant messages
        history = []
        for i in range(10):
            history.append({"role": "user", "content": f"User {i+1}"})
            history.append({"role": "assistant", "content": f"Assistant {i+1}"})
            
        # Mock directory.get_context to return this history
        self.agent.directory.get_context.return_value = json.dumps(history)
        
        # Call _prepare_messages
        messages = self.agent._prepare_messages("test_agent", "test_user")
        
        # Expected behavior:
        # We have 10 user messages: User 1 to User 10.
        # Indices in history: 0, 2, 4, 6, 8, 10, 12, 14, 16, 18
        # 5th last user message is User 6 (index 10).
        # We want everything AFTER User 6.
        # So we should start from index 11 (Assistant 6).
        # Wait, the requirement says "take messages after the 5th last message with role:user".
        # 5th last user message is User 6.
        # So we should keep Assistant 6, User 7, Assistant 7, ..., User 10, Assistant 10.
        
        # Let's verify what's in messages
        # First message should be System Prompt
        self.assertEqual(messages[0]['role'], 'system')
        self.assertEqual(messages[0]['content'], 'System Prompt')
        
        # The rest should be the filtered history
        filtered_history = messages[1:]
        
        # Check the first message of the filtered history
        # It should be Assistant 6
        self.assertEqual(filtered_history[0]['role'], 'assistant')
        self.assertEqual(filtered_history[0]['content'], 'Assistant 6')
        
        # Check the last message
        self.assertEqual(filtered_history[-1]['role'], 'assistant')
        self.assertEqual(filtered_history[-1]['content'], 'Assistant 10')
        
        # Count user messages in filtered history
        user_msgs = [m for m in filtered_history if m['role'] == 'user']
        # Should be User 7, 8, 9, 10 -> 4 messages
        self.assertEqual(len(user_msgs), 4)
        self.assertEqual(user_msgs[0]['content'], 'User 7')

    @patch('worker_agent.agent.agent.get_system_prompt')
    def test_prepare_messages_less_than_5(self, mock_get_system_prompt):
        mock_get_system_prompt.return_value = "System Prompt"
        
        # Create a history with 3 user messages
        history = []
        for i in range(3):
            history.append({"role": "user", "content": f"User {i+1}"})
            history.append({"role": "assistant", "content": f"Assistant {i+1}"})
            
        self.agent.directory.get_context.return_value = json.dumps(history)
        
        messages = self.agent._prepare_messages("test_agent", "test_user")
        
        # Should keep all messages
        filtered_history = messages[1:]
        self.assertEqual(len(filtered_history), 6)
        self.assertEqual(filtered_history[0]['content'], 'User 1')

if __name__ == '__main__':
    unittest.main()
