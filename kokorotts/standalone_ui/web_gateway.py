"""Browser access to speech routes, separate from the server-local native API."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import quote, urlsplit

from filelock import FileLock
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html

from kokorotts.admin_auth import AdminStorageError, AdminStore
from .admin import _cookie_name as admin_cookie_name

browser_script_owner: ContextVar[str | None] = ContextVar("browser_script_owner", default=None)
VISITOR_SECONDS = 30 * 24 * 60 * 60
PUBLIC_GET = {
    "/tts/defaults", "/tts/status", "/tts/formats", "/tts/stream-formats",
    "/tts/languages", "/tts/samples", "/tts/speakers", "/tts/voices", "/tts/ssml/capabilities",
}
PUBLIC_POST = {"/tts/generate", "/tts/stream", "/tts/tokenize", "/tts/metrics", "/tts/magic/render", "/tts/magic/take", "/tts/magic/assemble-upload"}
LIBRARY_PREFIXES = ("/tts/dialogue-scripts", "/tts/dialogue-workspaces", "/tts/dialogue-script-folders")


def _prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


class BrowserSessions:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(path) + ".lock", timeout=10):
            if not path.exists():
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(secrets.token_bytes(32))
                    handle.flush()
                    os.fsync(handle.fileno())
            self.secret = path.read_bytes()
        if len(self.secret) != 32:
            raise ValueError("Invalid browser session secret")

    @staticmethod
    def cookie_name(request: Request) -> str:
        return "__Host-solqi_web" if request.url.scheme == "https" else "solqi_web_local"

    def issue(self) -> str:
        claim = f"{int(time.time()) + VISITOR_SECONDS}.{secrets.token_urlsafe(24)}"
        signature = hmac.new(self.secret, claim.encode(), hashlib.sha256).hexdigest()
        return claim + "." + signature

    def verify(self, token: str | None) -> str | None:
        match = re.fullmatch(r"([0-9]{10,12})\.([A-Za-z0-9_-]{32})\.([0-9a-f]{64})", token or "")
        if not match or int(match[1]) <= time.time():
            return None
        claim = match[1] + "." + match[2]
        expected = hmac.new(self.secret, claim.encode(), hashlib.sha256).hexdigest()
        return match[2] if hmac.compare_digest(expected, match[3]) else None

    def cookie_header(self, request: Request, token: str) -> bytes:
        response = Response()
        response.set_cookie(self.cookie_name(request), token, max_age=VISITOR_SECONDS, httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/")
        return response.headers["set-cookie"].encode("latin-1")


class WebGateway:
    def __init__(self, app, *, sessions: BrowserSessions, admin_store: AdminStore, page_paths: set[str], schema_provider):
        self.app = app
        self.sessions = sessions
        self.admin_store = admin_store
        self.page_paths = page_paths | {"/admin", "/admin/login"}
        self.schema_provider = schema_provider

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = scope["path"]
        gateway = path.startswith("/web/")
        page = path.rstrip("/") in self.page_paths or path == "/"
        if not gateway and not page:
            return await self.app(scope, receive, send)

        token = request.cookies.get(self.sessions.cookie_name(request))
        owner = self.sessions.verify(token)
        new_cookie = None
        if page and owner is None:
            token = self.sessions.issue()
            owner = self.sessions.verify(token)
            new_cookie = self.sessions.cookie_header(request, token)

        async def guarded_send(message):
            if message["type"] == "http.response.start":
                headers = [(key, value) for key, value in message.get("headers", []) if key.lower() != b"cache-control"]
                headers.append((b"cache-control", b"private, no-store"))
                if new_cookie is not None:
                    headers.append((b"set-cookie", new_cookie))
                message = {**message, "headers": headers}
            await send(message)

        if not gateway:
            return await self.app(scope, receive, guarded_send)

        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, guarded_send)

        target = path[4:]
        if any(part in {".", ".."} for part in target.split("/")) or "\\" in target or "\x00" in target:
            return await reject(403, "Đường dẫn không hợp lệ.")
        session_probe = target == "/session" and scope["method"] == "GET"
        if not session_probe and not any(_prefix(target, prefix) for prefix in ("/tts", "/system", "/v1", "/health")):
            return await reject(404, "Không tìm thấy chức năng này.")
        method = scope["method"]
        library = any(_prefix(target, prefix) for prefix in LIBRARY_PREFIXES)
        public = session_probe or (
            (method in {"GET", "HEAD"} and target in PUBLIC_GET)
            or (method == "POST" and target in PUBLIC_POST)
            or (library and method in {"GET", "POST", "PUT", "PATCH", "DELETE"})
        )
        admin = None
        if not public or library or session_probe:
            try:
                admin = await run_in_threadpool(self.admin_store.session, request.cookies.get(admin_cookie_name(request)))
            except AdminStorageError:
                return await reject(503, "Không đọc được tài khoản quản trị.")
        if not public and admin is None:
            return await reject(401, "Vui lòng đăng nhập quản trị.")
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        expected_origin = urlsplit(str(request.url))

        def matches_origin(source):
            try:
                supplied = urlsplit(source or "")
                return supplied.scheme.lower() == expected_origin.scheme.lower() and supplied.netloc.lower() == expected_origin.netloc.lower()
            except ValueError:
                return False

        site = request.headers.get("sec-fetch-site")
        legacy_browser = site is None and matches_origin(origin or referer)
        admin_navigation = admin is not None and site == "none" and method in {"GET", "HEAD"}
        if site != "same-origin" and not legacy_browser and not admin_navigation:
            return await reject(403, "Vui lòng sử dụng chức năng này trên trang đọc.")
        if origin and not matches_origin(origin):
            return await reject(403, "Yêu cầu không được gửi từ trang đọc.")
        if method not in {"GET", "HEAD"} and not matches_origin(origin or referer):
            return await reject(403, "Yêu cầu không được gửi từ trang đọc.")
        if owner is None:
            if admin is None:
                return await reject(403, "Vui lòng mở lại trang đọc để tiếp tục.")
            token = self.sessions.issue()
            owner = self.sessions.verify(token)
            new_cookie = self.sessions.cookie_header(request, token)

        if session_probe:
            return await JSONResponse({"authenticated": admin is not None})(scope, receive, guarded_send)

        if target == "/tts/openapi.json":
            schema = {**self.schema_provider(), "servers": [{"url": "/web"}]}
            return await JSONResponse(schema)(scope, receive, guarded_send)
        if target == "/tts/docs":
            response = get_swagger_ui_html(openapi_url="/web/tts/openapi.json", title="SolQi-TTS API", oauth2_redirect_url="/web/tts/docs/oauth2-redirect")
            return await response(scope, receive, guarded_send)
        if target == "/tts/redoc":
            return await get_redoc_html(openapi_url="/web/tts/openapi.json", title="SolQi-TTS API")(scope, receive, guarded_send)
        if target == "/tts/docs/oauth2-redirect":
            return await get_swagger_ui_oauth2_redirect_html()(scope, receive, guarded_send)

        forwarded = {**scope, "path": target, "raw_path": quote(target, safe="/:@-._~!$&'()*+,;=").encode("ascii")}
        context = browser_script_owner.set(None if admin is not None else owner)
        try:
            await self.app(forwarded, receive, guarded_send)
        finally:
            browser_script_owner.reset(context)
