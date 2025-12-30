from aiohttp import web
from google_oauth_handler import get_authorization_url, exchange_code_for_credentials
from user_manager import store_google_credentials
import urllib.parse

async def handle_login(request):
    """Redirect to Google Login."""
    user_id = request.query.get('user_id')
    if not user_id:
        return web.Response(text="Missing user_id", status=400)
        
    try:
        url = get_authorization_url(user_id)
        raise web.HTTPFound(url)
    except Exception as e:
        return web.Response(text=f"Error generating login URL: {e}", status=500)

async def handle_oauth_callback(request):
    """Handle the OAuth callback from Google."""
    code = request.query.get('code')
    error = request.query.get('error')
    state = request.query.get('state') # This contains user_id
    
    if error:
        return web.Response(text=f"Authentication Failed: {error}", status=200) # User friendly error
        
    if not code:
        return web.Response(text="Missing auth code", status=400)
    
    if not state:
        return web.Response(text="Missing state (user_id)", status=400)
        
    user_id = state
    
    try:
        # Exchange code
        creds_data = exchange_code_for_credentials(code)
        
        # Store in DB
        success = store_google_credentials(user_id, creds_data)
        
        if success:
            return web.Response(text="<h1>Connection Successful!</h1><p>You can close this window and return to Zarie.</p>", content_type='text/html')
        else:
            return web.Response(text="Error storing credentials in database.", status=500)
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.Response(text=f"Error exchanging code: {str(e)}", status=500)

def get_oauth_app():
    """Create the aiohttp application."""
    app = web.Application()
    app.router.add_get('/google/login', handle_login)
    app.router.add_get('/google/callback', handle_oauth_callback)
    return app
