import asyncio
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime
from zoneinfo import ZoneInfo
from agent.agent import Agent

class TestAgentRaceCondition(unittest.TestCase):
    def setUp(self):
        self.agent = Agent(":memory:")
        # Mock dependencies
        self.agent.state = MagicMock()
        self.agent.state.add_context = MagicMock()
        self.agent.state.get_messages.return_value = []
        self.agent.state.get_running_summary.return_value = ""
        self.agent._ensure_tools_initialized = AsyncMock()
        self.agent._prepare_messages = AsyncMock(return_value=[])
        
        # Mock the internal streaming loop to capture arguments passed to it
        # NOTE: Must use MagicMock (not AsyncMock) for async generators, because AsyncMock forces return value to be a coroutine.
        self.agent._react_loop_streaming = MagicMock()
        # We need _react_loop_streaming to yield something effectively to simulate a generator
        async def mock_generator(*args, **kwargs):
            yield "chunk"
        self.agent._react_loop_streaming.side_effect = mock_generator

    def test_concurrent_invoke_statelessness(self):
        async def run_test():
            # Setup two different users with different contexts
            user_a = "user_A"
            time_a = datetime(2025, 1, 1, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
            
            user_b = "user_B"
            time_b = datetime(2025, 1, 1, 22, 0, 0, tzinfo=ZoneInfo("UTC"))
            
            # Helper wrapper to call invoke and capture args passed to _react_loop_streaming
            async def call_invoke(user, time):
                # We need to spy on the call to _react_loop_streaming
                # But since it's an async generator, we can't easily spy on the *generator object creation* arguments 
                # unless we patch the method on the class or instance.
                # We already patched self.agent._react_loop_streaming.
                
                # Iterate through the generator
                async for chunk in self.agent.invoke(user, "msg", "medium", timestamp=time):
                    pass

            # Create tasks
            task_a = asyncio.create_task(call_invoke(user_a, time_a))
            task_b = asyncio.create_task(call_invoke(user_b, time_b))
            
            await asyncio.gather(task_a, task_b)
            
            # Verify calls
            # _react_loop_streaming should be called twice
            self.assertEqual(self.agent._react_loop_streaming.call_count, 2)
            
            # Check arguments for each call
            # call_args_list is a list of calls. Order depends on async scheduling, so we check existence.
            calls = self.agent._react_loop_streaming.call_args_list
            
            found_a = False
            found_b = False
            
            for call in calls:
                args, kwargs = call
                # args[0] is messages, args[1] is user_id, args[2] is timezone
                # kwargs should contain timestamp
                
                start_user_id = args[1]
                start_timestamp = kwargs.get('timestamp')
                
                if start_user_id == user_a:
                    self.assertEqual(start_timestamp, time_a)
                    found_a = True
                elif start_user_id == user_b:
                    self.assertEqual(start_timestamp, time_b)
                    found_b = True
            
            self.assertTrue(found_a, "Did not find call for User A with correct timestamp")
            self.assertTrue(found_b, "Did not find call for User B with correct timestamp")
            
            # Verify NO instance state was set (heuristic check, though we removed the code)
            self.assertFalse(hasattr(self.agent, '_current_timestamp'), "Agent still has _current_timestamp")
            
        asyncio.run(run_test())

if __name__ == "__main__":
    test = TestAgentRaceCondition()
    test.setUp()
    test.test_concurrent_invoke_statelessness()
    print("Verification Passed!")
