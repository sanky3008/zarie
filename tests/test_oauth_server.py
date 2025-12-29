import unittest
from unittest.mock import patch, MagicMock
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
import asyncio
from aiohttp import web
import sys
import os

# Mock Google libs
sys.modules['google_auth_oauthlib.flow'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()

# Import the server handler (not yet created)
try:
    from oauth_server import handle_oauth_callback, handle_login, get_oauth_app
except ImportError:
    pass

class TestOAuthServer(AioHTTPTestCase):
    
    async def get_application(self):
        """Create web app for testing."""
        app = web.Application()
        # Register the handler we want to test
        try:
            app.router.add_get('/google/callback', handle_oauth_callback)
        except NameError:
            pass # Module not imported yet
        return app
    
    @unittest_run_loop
    @patch('oauth_server.exchange_code_for_credentials')
    @patch('oauth_server.store_google_credentials')
    async def test_callback_success(self, mock_store, mock_exchange):
        """Test successful callback."""
        # Setup mocks
        mock_exchange.return_value = {'token': '123'}
        mock_store.return_value = True
        
        # Request
        async with self.client.request("GET", "/google/callback?code=abc&state=user_1") as resp:
            self.assertEqual(resp.status, 200)
            text = await resp.text()
            self.assertIn("Connection Successful", text)
            
        # Verify calls
        mock_exchange.assert_called_with("abc")
        mock_store.assert_called_with("user_1", {'token': '123'})
        
    @unittest_run_loop
    async def test_callback_error(self):
        """Test error from Google."""
        async with self.client.request("GET", "/google/callback?error=access_denied") as resp:
             # Should probably still be 200 OK but with error message, or 400?
             # Let's say we handle it gracefully with a 200 and a message.
             self.assertEqual(resp.status, 200) 
             text = await resp.text()
             self.assertIn("Authentication Failed", text)

if __name__ == '__main__':
    unittest.main()
