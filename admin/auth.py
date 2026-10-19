import hmac
import secrets
import time

from aiohttp import web

import config

COOKIE = "wegram_session"
WINDOW = 60
SESSION_TTL = 12 * 60 * 60

_sessions = {}
_login_at = {}


def client_ip(request) -> str:
    return request.remote or "unknown"


def allow_login(ip: str) -> bool:
    now = time.monotonic()
    last = _login_at.get(ip)
    if last is not None and now - last < WINDOW:
        return False
    _login_at[ip] = now
    return True


def configured() -> bool:
    admin = config.cfg.admin
    return bool(admin.username and admin.password)


def check_password(username: str, password: str) -> bool:
    admin = config.cfg.admin
    user_ok = hmac.compare_digest(username.encode(), admin.username.encode())
    pass_ok = hmac.compare_digest(password.encode(), admin.password.encode())
    return user_ok and pass_ok


def issue() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL
    return token


def drop(token: str) -> None:
    _sessions.pop(token, None)


def valid(token: str) -> bool:
    if not token:
        return False
    expires = _sessions.get(token)
    if not expires or expires < time.time():
        _sessions.pop(token, None)
        return False
    return True


def read_token(request) -> str:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return request.cookies.get(COOKIE, "")


def attach(response, token: str):
    response.set_cookie(COOKIE, token, httponly=True, samesite="Lax", path="/", max_age=SESSION_TTL)
    return response


def clear_cookie(response):
    response.del_cookie(COOKIE, path="/")
    return response


def require(request):
    if valid(read_token(request)):
        return None
    return web.json_response({"ok": False, "message": "请先登录"}, status=401)
