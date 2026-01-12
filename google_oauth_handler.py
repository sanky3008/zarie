from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os

# Scopes required for the application
SCOPES = [
    'https://www.googleapis.com/auth/calendar'
]

def get_oauth_flow():
    """Create and return a Flow instance."""
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    redirect_uri = os.getenv('GOOGLE_REDIRECT_URI')
    
    if not client_id or not client_secret or not redirect_uri:
        raise ValueError("Google OAuth keys (CLIENT_ID, CLIENT_SECRET, REDIRECT_URI) missing in .env")
    
    # Create client config dictionary
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    return flow

def get_authorization_url(user_id: str):
    """Generate authorization URL for a specific user."""
    flow = get_oauth_flow()
    # Pass user_id in state to identify them on callback
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        state=user_id,
        prompt='consent' # Force consent to get refresh token
    )
    return authorization_url

def exchange_code_for_credentials(code: str):
    """Exchange auth code for credentials."""
    flow = get_oauth_flow()
    flow.fetch_token(code=code)
    
    creds = flow.credentials
    return {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes,
        'expiry': creds.expiry.isoformat() if creds.expiry else None
    }

def get_google_service(user_id: str, service_name: str, version: str = 'v1'):
    """Get an authenticated Google service client."""
    from user_manager import get_google_credentials
    
    creds_data = get_google_credentials(user_id)
    if not creds_data:
        return None
        
    creds = Credentials(
        token=creds_data.get('token'),
        refresh_token=creds_data.get('refresh_token'),
        token_uri=creds_data.get('token_uri'),
        client_id=creds_data.get('client_id'),
        client_secret=creds_data.get('client_secret'),
        scopes=creds_data.get('scopes'),
        expiry=creds_data.get('expiry') # DateTime or string? Credentials expects datetime usually?
        # Credentials handles expiry parsing if it's correct type. 
        # If we stored as string isoformat, we might need to parse back.
        # But wait, google.oauth2.credentials.Credentials constructor docs?
        # Let's hope it's robust or handle it. 
        # Actually, expiry from DB is string. Credentials expects datetime object if I recall. 
        # Let's check or be safe. 
    )
    
    # Handle expiry parsing if needed
    if isinstance(creds_data.get('expiry'), str):
        from datetime import datetime
        try:
            creds.expiry = datetime.fromisoformat(creds_data.get('expiry'))
        except:
            pass
            
    try:
        service = build(service_name, version, credentials=creds)
        return service
    except Exception as e:
        print(f"Error building Google service: {e}")
        return None
