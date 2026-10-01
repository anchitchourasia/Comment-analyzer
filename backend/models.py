from typing import Optional
from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str = "ok"
    mode: str = "local_dev"

class ErrorResponse(BaseModel):
    detail: str

class UserSessionModel(BaseModel):
    user_id: str
    account_label: str = "Google account connected"
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    selected_channel_id: Optional[str] = None
    selected_channel_title: Optional[str] = None
    selected_channel_handle: Optional[str] = None
    channel_connection_status: str = "unconnected"
    has_write_scope: bool = True
    granted_scopes: Optional[str] = None
    verified_channels: list[str] = []
    channel_titles: dict[str, str] = {}

class PostRequest(BaseModel):
    answer_text: str
    question_key: Optional[str] = None
    occurrence_id: Optional[str] = None
    live_chat_id: Optional[str] = None
    auto_reply_opt_in: bool = True
    record_id: Optional[str] = None

class PostResponse(BaseModel):
    status: str
    message: str
    youtube_message_id: Optional[str] = None
    live_chat_id: Optional[str] = None
    error_reason: Optional[str] = None

class LoginInitResponse(BaseModel):
    auth_url: str
    state: str

class LoginCallbackRequest(BaseModel):
    code: str
    state: str

class LoginCallbackResponse(BaseModel):
    status: str
    session_token: str
    user_id: str

class OAuthInitResponse(BaseModel):
    auth_url: str
    state: str

class OAuthCallbackRequest(BaseModel):
    code: str
    state: str

class ChannelInfo(BaseModel):
    id: str
    title: str
    handle: Optional[str] = None

class OAuthCallbackResponse(BaseModel):
    status: str
    channels: list[ChannelInfo] = []

class ChannelSelectRequest(BaseModel):
    channel_id: str

class ChannelSelectResponse(BaseModel):
    status: str
    channel_id: str
    channel_title: str

class DisconnectResponse(BaseModel):
    status: str
