from dash_auth_external import DashAuthExternal

from settings import AUTH_URL, TOKEN_URL, APP_URL, CLIENT_ID, CLIENT_SECRET

import logging
logger = logging.getLogger(__name__)

auth = DashAuthExternal(
    external_auth_url=AUTH_URL,
    external_token_url=TOKEN_URL,
    app_url=APP_URL,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    with_pkce=True,
)
server = auth.server  # expose the Flask server for app.py
