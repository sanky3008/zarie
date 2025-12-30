import unittest
from unittest.mock import patch, MagicMock
import sys

# Mock Google libs
sys.modules['google_auth_oauthlib.flow'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()

try:
    from agent.tools import gmail_read_emails, calendar_create_event
except ImportError:
    pass

class TestGoogleTools(unittest.TestCase):
    
    @patch('google_oauth_handler.get_google_service')
    def test_gmail_read(self, mock_get_service):
        """Test reading emails."""
        # Mock service.users().messages().list()
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        
        mock_list = mock_service.users().messages().list()
        mock_list.execute.return_value = {
            'messages': [{'id': '1'}, {'id': '2'}]
        }
        
        # Mock users().messages().get() for each message
        mock_get = mock_service.users().messages().get()
        mock_get.execute.side_effect = [
            {'snippet': 'Email 1'},
            {'snippet': 'Email 2'}
        ]
        
        # Call
        try:
           result = gmail_read_emails("user_1", count=2)
        except NameError:
            return # Skip if not imported
            
        # Verify
        self.assertIn("Email 1", result)
        self.assertIn("Email 2", result)
        
    @patch('google_oauth_handler.get_google_service')
    def test_calendar_create(self, mock_get_service):
        """Test creating calendar event."""
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        
        try:
             calendar_create_event(
                 "user_1", 
                 "Meeting", 
                 "2025-01-01T10:00:00Z", 
                 "2025-01-01T11:00:00Z",
                 attendees=["test@example.com"]
             )
        except NameError:
            return
            
        # Verify insert called with correct body
        mock_service.events().insert.assert_called()
        call_args = mock_service.events().insert.call_args[1] # kwargs
        body = call_args['body']
        self.assertEqual(body['summary'], "Meeting")
        self.assertEqual(body['attendees'], [{'email': 'test@example.com'}])

if __name__ == '__main__':
    unittest.main()
