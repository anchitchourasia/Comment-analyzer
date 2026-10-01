import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

REDIRECT_URI_LOGIN = os.environ.get("REDIRECT_URI_LOGIN", "http://localhost:8000/api/auth/login/callback").strip()
REDIRECT_URI_YOUTUBE = os.environ.get("REDIRECT_URI_YOUTUBE", "http://localhost:8000/api/oauth/callback").strip()

PLACEHOLDER_VALUES = {
    "",
    "mock-client-id",
    "mock-client-secret",
    "server_app_client_id.apps.googleusercontent.com",
    "your_google_client_id_here",
    "your_google_client_secret_here"
}

def is_oauth_configured() -> bool:
    """Returns True if valid non-placeholder Google Client ID & Secret are set."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID).strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET).strip()

    if not client_id or not client_secret:
        return False
    if client_id.lower() in PLACEHOLDER_VALUES or client_secret.lower() in PLACEHOLDER_VALUES:
        return False
    if client_id.startswith("mock-") or client_secret.startswith("mock-"):
        return False
    return True

def get_client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID).strip()

def get_client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET).strip()
