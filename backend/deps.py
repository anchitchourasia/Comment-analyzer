from fastapi import HTTPException, Request, Depends, status
from backend.models import UserSessionModel


# In-memory session store (empty by default in M2 local-dev)
# Maps session_token -> UserSessionModel
session_store = {}

async def get_current_user(request: Request) -> UserSessionModel:
    """Verify session token from header or cookie. FAILS CLOSED (401) if unauthenticated."""
    token = request.headers.get("x-session-token") or request.cookies.get("session")
    if not token or token not in session_store:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return session_store[token]

async def get_authorized_channel(channel_id: str, current_user: UserSessionModel = Depends(get_current_user)) -> str:
    """Enforce strict application-level channel data authorization.

    A user can only access or modify application state (pending queue, Q&A data, settings)
    in channel data directories that they own (selected_channel_id or verified_channels).
    FAILS CLOSED (403) if channel_id is not authorized for current_user.
    """
    if not channel_id or not isinstance(channel_id, str):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid target channel ID.")
    ch = channel_id.strip()
    if ch not in current_user.verified_channels and ch != current_user.selected_channel_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Channel {ch!r} is not authorized for this user session."
        )
    return ch

