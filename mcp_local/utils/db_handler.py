import os
import yaml
import bcrypt

_USERS_PATH = os.path.join(os.path.dirname(__file__), "..", "users.yaml")

def _load() -> dict:
    with open(_USERS_PATH) as f:
        return yaml.safe_load(f) or {}

def _save(data: dict):
    with open(_USERS_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False)


def get_user_by_email(email: str) -> dict | None:
    data = _load()
    users = data.get("credentials", {}).get("usernames", {})
    for user in users.values():
        if user.get("email", "").lower() == email.lower():
            return user
    return None


def authenticate_user(email: str, password: str) -> bool:
    user = get_user_by_email(email)
    if user:
        return bcrypt.checkpw(password.encode(), user["password"].encode())
    return False


def verify_duplicate_user(email: str) -> bool:
    data = _load()
    users = data.get("credentials", {}).get("usernames", {})
    return any(u.get("email", "").lower() == email.lower() for u in users.values())


def save_user(email: str, password: str, extra_input_params: dict = None):
    data = _load()
    if "credentials" not in data:
        data["credentials"] = {}
    if "usernames" not in data["credentials"]:
        data["credentials"]["usernames"] = {}

    username = email.split("@")[0].lower().replace(".", "_")
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    data["credentials"]["usernames"][username] = {
        "name": username,
        "email": email,
        "password": hashed,
        "role": "viewer",
    }
    _save(data)


def get_users():
    data = _load()
    return list(data.get("credentials", {}).get("usernames", {}).values())
