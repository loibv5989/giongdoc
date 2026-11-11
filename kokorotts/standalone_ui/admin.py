"""Authenticated operator pages and APIs, separate from speech clients."""

from __future__ import annotations

import ipaddress
import hmac
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from kokorotts.admin_auth import AdminStorageError, AdminStore, LoginThrottle, SESSION_SECONDS
from kokorotts.catalog import model_family_inventory

TEMPLATE = Path(__file__).parent / "templates" / "admin.html"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class ModelsInput(BaseModel):
    model_families: list[str] = Field(min_length=1, max_length=5)


def _cookie_name(request: Request) -> str:
    return "__Host-solqi_admin" if request.url.scheme == "https" else "solqi_admin_local"


def _same_origin(request: Request) -> None:
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Yêu cầu không hợp lệ. Hãy tải lại trang quản trị.")
    source = request.headers.get("origin") or request.headers.get("referer")
    if source:
        origin = urlsplit(source)
        target = urlsplit(str(request.url))
        if origin.scheme.lower() != target.scheme.lower() or origin.netloc.lower() != target.netloc.lower():
            raise HTTPException(403, "Yêu cầu không hợp lệ. Hãy tải lại trang quản trị.")


def _https_or_local(request: Request) -> None:
    if request.url.scheme == "https":
        return
    try:
        address = ipaddress.ip_address(request.client.host)
        local_client = address.is_loopback or bool(getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback)
    except (ValueError, AttributeError):
        local_client = False
    if not local_client or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(400, "Vui lòng dùng HTTPS để đăng nhập quản trị.")


async def _payload(request: Request, schema: type[BaseModel]) -> BaseModel:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "Yêu cầu không hợp lệ.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8192:
            raise HTTPException(413, "Nội dung yêu cầu quá dài.")
    try:
        return schema.model_validate(json.loads(body), strict=True)
    except (ValueError, UnicodeDecodeError, ValidationError) as exc:
        raise HTTPException(422, "Vui lòng kiểm tra lại thông tin đã nhập.") from exc


def _page(view: str, configured: bool) -> HTMLResponse:
    text = TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("{{ADMIN_VIEW}}", view)
    text = text.replace("{{LOGIN_HIDDEN}}", "hidden" if view != "login" else "")
    text = text.replace("{{DASHBOARD_HIDDEN}}", "hidden" if view != "dashboard" else "")
    text = text.replace("{{SETUP_HIDDEN}}", "hidden" if configured else "")
    text = text.replace("{{LOGIN_DISABLED}}", "" if configured else "disabled")
    response = HTMLResponse(text)
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response


def attach_admin(app, *, runtime, status_provider, store: AdminStore | None = None) -> AdminStore:
    account_path = os.getenv("KOKOROTTS_ADMIN_PATH") or runtime.settings.path.with_name("admin.json")
    store = store or AdminStore(account_path)
    throttle = LoginThrottle()
    router = APIRouter(prefix="/admin", include_in_schema=False)

    def models_payload() -> dict:
        return {"supported": model_family_inventory(), "enabled": runtime.served_model_families}

    @app.middleware("http")
    async def protect_admin(request: Request, call_next):
        path = request.url.path.rstrip("/") or "/"
        operator = path == "/system" or path.startswith("/system/") or path == "/tts/purge"
        private_api = path.startswith("/admin/api/") and path != "/admin/api/login"
        admin_page = path == "/admin" or path.startswith("/admin/")
        try:
            request.state.admin_session = None
            if operator or private_api or path in {"/admin", "/admin/login"}:
                token = request.cookies.get(_cookie_name(request))
                session = await run_in_threadpool(store.session, token)
                request.state.admin_session = session
                request.state.admin_token = token
                if operator or private_api:
                    if session is None:
                        raise HTTPException(401, "Vui lòng đăng nhập quản trị.")
                    if request.method not in SAFE_METHODS:
                        _same_origin(request)
                        if not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), session.csrf_token.encode()):
                            raise HTTPException(403, "Phiên làm việc không hợp lệ. Hãy tải lại trang quản trị.")
            response = await call_next(request)
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        except AdminStorageError:
            response = JSONResponse({"detail": "Không đọc được tài khoản quản trị."}, status_code=503)
        if admin_page or operator:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "same-origin"
        return response

    @router.get("")
    def dashboard(request: Request):
        if request.state.admin_session is None:
            return RedirectResponse("/admin/login", status_code=303)
        return _page("dashboard", store.configured)

    @router.get("/login")
    def login_page(request: Request):
        if request.state.admin_session is not None:
            return RedirectResponse("/admin", status_code=303)
        return _page("login", store.configured)

    @router.post("/api/login")
    async def login(request: Request):
        _https_or_local(request)
        _same_origin(request)
        if not store.configured:
            raise HTTPException(503, "Tài khoản quản trị chưa được thiết lập.")
        client = request.client.host if request.client else "unknown"
        if not throttle.allow(client):
            return JSONResponse({"detail": "Bạn đã thử đăng nhập nhiều lần. Vui lòng thử lại sau vài phút."}, status_code=429, headers={"Retry-After": "300"})
        payload = await _payload(request, LoginInput)
        result = await run_in_threadpool(store.login, payload.username.strip(), payload.password)
        if result is None:
            raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng.")
        token, session = result
        response = JSONResponse({"username": session.username, "csrf_token": session.csrf_token})
        response.set_cookie(_cookie_name(request), token, max_age=SESSION_SECONDS, httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/")
        return response

    @router.get("/api/session")
    def session_info(request: Request):
        session = request.state.admin_session
        return {"username": session.username, "csrf_token": session.csrf_token, "expires": session.expires}

    @router.post("/api/logout")
    def logout(request: Request):
        store.logout(request.state.admin_token)
        response = JSONResponse({"ok": True})
        response.delete_cookie(_cookie_name(request), path="/", httponly=True, secure=request.url.scheme == "https", samesite="strict")
        return response

    @router.get("/api/status")
    def admin_status():
        return status_provider()

    @router.get("/api/models")
    def model_settings():
        return models_payload()

    @router.put("/api/models")
    async def save_models(request: Request):
        payload = await _payload(request, ModelsInput)
        try:
            await run_in_threadpool(runtime.set_served_model_families, payload.model_families)
        except ValueError as exc:
            raise HTTPException(400, "Danh sách model không hợp lệ. Phải giữ ít nhất một nhóm giọng.") from exc
        return models_payload()

    @router.post("/api/models/purge")
    def purge_models():
        purged, remaining = runtime.purge()
        return {"purged": purged, "remaining": remaining}

    app.include_router(router)
    app.state.admin_store = store
    return store
