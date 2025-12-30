import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Mock Google libs before importing handler
sys.modules['google_auth_oauthlib.flow'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()

# Now import
try:
    from google_oauth_handler import get_authorization_url, exchange_code_for_credentials, get_google_service
except ImportError:
    pass

class TestGoogleAuthLogic(unittest.TestCase):
    
    @patch('google_oauth_handler.Flow')
    @patch.dict(os.environ, {
        "GOOGLE_CLIENT_ID": "dummy_client", 
        "GOOGLE_CLIENT_SECRET": "dummy_secret",
        "GOOGLE_REDIRECT_URI": "dummy_uri"
    })
    def test_get_authorization_url(self, MockFlow):
        """Test URL generation."""
        # Setup mock
        mock_flow_instance = MagicMock()
        MockFlow.from_client_config.return_value = mock_flow_instance
        mock_flow_instance.authorization_url.return_value = ("http://auth.url", "state_123")
        
        # Call
        url = get_authorization_url("user_1")
        
        # Verify
        self.assertEqual(url, "http://auth.url")
        MockFlow.from_client_config.assert_called_once()
        # Verify redirect_uri was passed
        args, kwargs = MockFlow.from_client_config.call_args
        # kwargs might contain redirect_uri? Or it's set on the instance.
        self.assertEqual(kwargs['redirect_uri'], "dummy_uri")

    @patch('google_oauth_handler.Flow')
    @patch.dict(os.environ, {
        "GOOGLE_CLIENT_ID": "dummy_client", 
        "GOOGLE_CLIENT_SECRET": "dummy_secret",
        "GOOGLE_REDIRECT_URI": "dummy_uri"
    })
    def test_exchange_code(self, MockFlow):
        """Test token exchange."""
        mock_flow_instance = MagicMock()
        MockFlow.from_client_config.return_value = mock_flow_instance
        
        mock_creds = MagicMock()
        mock_creds.token = "tok_123"
        mock_creds.refresh_token = "ref_123"
        mock_creds.to_json.return_value = "{}"
        mock_creds.token_uri = "uri"
        mock_creds.client_id = "cid"
        mock_creds.client_secret = "csec"
        mock_creds.scopes = ["scope1"]
        mock_creds.expiry = None
        
        # We expect get_google_credentials to return a dict, so logic should convert creds object to dict
        mock_flow_instance.credentials = mock_creds
        
        # Call
        result_creds = exchange_code_for_credentials("fake_code")
        
        # Verify
        mock_flow_instance.fetch_token.assert_called_with(code="fake_code")
        self.assertEqual(result_creds['token'], "tok_123")
        self.assertEqual(result_creds['refresh_token'], "ref_123")

if __name__ == '__main__':
    unittest.main()
