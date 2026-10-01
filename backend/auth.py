import os
import json
import base64
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet
from backend.storage import BASE_DIR, DATA_DIR

USERS_DIR = DATA_DIR / "users"

def _get_fernet_key() -> bytes:
    """Retrieve or derive Fernet encryption key from environment ENCRYPTION_KEY."""
    raw_key = os.environ.get("ENCRYPTION_KEY", "default-antigravity-dev-secret-key-do-not-use-in-prod")
    key_bytes = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(key_bytes)

def encrypt_tokens(token_dict: dict) -> bytes:
    """Encrypt token dictionary to bytes using Fernet."""
    f = Fernet(_get_fernet_key())
    payload = json.dumps(token_dict).encode("utf-8")
    return f.encrypt(payload)

def decrypt_tokens(encrypted_bytes: bytes) -> dict:
    """Decrypt token bytes using Fernet and load JSON dictionary."""
    f = Fernet(_get_fernet_key())
    payload = f.decrypt(encrypted_bytes)
    return json.loads(payload.decode("utf-8"))

def get_user_channel_dir(user_id: str, channel_id: str) -> Path:
    """Return Path to data/users/{user_id}/channels/{channel_id}/."""
    clean_user = "".join(c for c in user_id if c.isalnum() or c in ("_", "-"))
    clean_channel = "".join(c for c in channel_id if c.isalnum() or c in ("_", "-"))
    u_dir = USERS_DIR / clean_user / "channels" / clean_channel
    u_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return u_dir

def save_user_tokens(user_id: str, channel_id: str, token_dict: dict) -> Path:
    """Encrypt and save token dict to user channel directory."""
    token_file = get_user_channel_dir(user_id, channel_id) / "token.enc"
    encrypted_bytes = encrypt_tokens(token_dict)
    
    # Atomic write
    tmp_file = token_file.with_name("token.tmp")
    tmp_file.write_bytes(encrypted_bytes)
    tmp_file.replace(token_file)
    return token_file

def load_user_tokens(user_id: str, channel_id: str) -> dict | None:
    """Load and decrypt user tokens. Returns None if missing or corrupt."""
    token_file = get_user_channel_dir(user_id, channel_id) / "token.enc"
    if not token_file.exists():
        return None
    try:
        encrypted_bytes = token_file.read_bytes()
        return decrypt_tokens(encrypted_bytes)
    except Exception:
        return None

def delete_user_tokens(user_id: str, channel_id: str) -> bool:
    """Delete encrypted token file on disconnect."""
    token_file = get_user_channel_dir(user_id, channel_id) / "token.enc"
    if token_file.exists():
        try:
            token_file.unlink()
            return True
        except OSError:
            return False
    return False
