from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.testclient import TestClient

from kokorotts.admin_auth import AdminStore
from kokorotts.standalone_ui.admin import attach_admin
from kokorotts.standalone_ui.script_api import attach_scripts
from kokorotts.standalone_ui.web_gateway import BrowserSessions, VISITOR_SECONDS, WebGateway
from tests.test_admin import FakeRuntime, PASSWORD


class WebGatewayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = AdminStore(self.root / "admin.json")
        self.store.create("admin", PASSWORD)
        self.sessions = BrowserSessions(self.root / "web-session.key")
        self.calls = 0
        self.app = FastAPI()

        @self.app.get("/")
        def index():
            return HTMLResponse("<title>SolQi-TTS</title>")

        @self.app.get("/tts/defaults")
        def defaults():
            return {"voice": "diem_trinh", "text": "Xin chào."}

        @self.app.post("/tts/generate")
        def speech():
            self.calls += 1
            return {"speech": True}

        @self.app.post("/tts/stream")
        def stream():
            return StreamingResponse(iter([b"first", b"second"]), media_type="audio/mpeg")

        @self.app.get("/system/settings")
        def settings():
            return {"private": True}

        @self.app.post("/system/models/purge")
        def purge():
            self.calls += 1
            return {"ok": True}

        attach_scripts(self.app, self.root / "scripts")
        attach_admin(self.app, runtime=FakeRuntime(self.root), status_provider=lambda: {}, store=self.store)
        self.app.add_middleware(WebGateway, sessions=self.sessions, admin_store=self.store, page_paths={"/"}, schema_provider=self.app.openapi)
        self.client = self.new_client()

    def new_client(self):
        client = TestClient(self.app, base_url="https://giongdoc.test")
        self.addCleanup(client.close)
        return client

    def browser(self, method, path, *, client=None, headers=None, **options):
        supplied = {"Sec-Fetch-Site": "same-origin", **(headers or {})}
        if method not in {"GET", "HEAD"}:
            supplied.setdefault("Origin", "https://giongdoc.test")
        return (client or self.client).request(method, path, headers=supplied, **options)

    def test_public_page_and_speech_do_not_require_admin_login(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        cookie = page.headers["set-cookie"]
        for flag in ["__Host-solqi_web=", "HttpOnly", "Secure", "SameSite=strict", "Path=/"]:
            self.assertIn(flag, cookie)
        self.assertIn("no-store", page.headers["cache-control"])
        self.assertIsNone(self.client.cookies.get("__Host-solqi_admin"))
        self.assertEqual(self.browser("GET", "/web/session").json(), {"authenticated": False})
        self.assertEqual(self.browser("GET", "/web/tts/defaults").json()["voice"], "diem_trinh")
        self.assertEqual(self.browser("POST", "/web/tts/generate", json={"text": "Xin chào."}).status_code, 200)
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.client.get("/tts/defaults").status_code, 200)

    def test_gateway_rejects_missing_forged_expired_and_cross_site_context(self):
        self.assertEqual(self.browser("GET", "/web/tts/defaults").status_code, 403)
        self.client.get("/")
        token = self.client.cookies.get("__Host-solqi_web")
        for headers in [{"Sec-Fetch-Site": "cross-site"}, {"Origin": "https://other.test"}]:
            self.assertEqual(self.browser("POST", "/web/tts/generate", headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/web/tts/defaults").status_code, 403)
        self.assertEqual(self.client.post("/web/tts/generate", headers={"Sec-Fetch-Site": "same-origin"}).status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.browser("GET", "/web/tts/defaults", headers={"Cookie": "__Host-solqi_web=" + token[:-1] + ("0" if token[-1] != "0" else "1")}).status_code, 403)
        with patch("kokorotts.standalone_ui.web_gateway.time.time", return_value=time.time() - VISITOR_SECONDS - 5):
            expired = self.sessions.issue()
        self.assertEqual(self.browser("GET", "/web/tts/defaults", headers={"Cookie": "__Host-solqi_web=" + expired}).status_code, 403)
        self.assertEqual(self.calls, 0)

    def test_older_browsers_may_use_same_origin_referer_but_other_sites_cannot(self):
        self.client.get("/")
        self.assertEqual(self.client.get("/web/tts/defaults", headers={"Referer": "https://giongdoc.test/"}).status_code, 200)
        self.assertEqual(self.client.post("/web/tts/generate", headers={"Referer": "https://giongdoc.test/"}).status_code, 200)
        self.assertEqual(self.client.get("/web/tts/defaults", headers={"Referer": "https://other.test/"}).status_code, 403)
        self.assertEqual(self.browser("GET", "/web/tts/defaults", headers={"Sec-Fetch-Site": "cross-site", "Referer": "https://giongdoc.test/"}).status_code, 403)

    def test_public_visitors_cannot_call_management_or_documentation(self):
        self.client.get("/")
        for path in ["/web/system/settings", "/web/tts/purge", "/web/tts/docs", "/web/tts/openapi.json", "/web/v1/models"]:
            self.assertEqual(self.browser("GET", path).status_code, 401, path)
        self.assertEqual(self.browser("GET", "/web/admin/api/session").status_code, 404)
        self.assertNotEqual(self.browser("GET", "/web/tts/%2e%2e/system/settings").status_code, 200)
        self.assertEqual(self.calls, 0)

    def test_admin_gateway_keeps_csrf_and_serves_browser_scoped_docs(self):
        self.client.get("/")
        login = self.browser("POST", "/admin/api/login", json={"username": "admin", "password": PASSWORD})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.browser("GET", "/web/session").json(), {"authenticated": True})
        self.assertEqual(self.browser("GET", "/web/system/settings").status_code, 200)
        self.assertEqual(self.browser("POST", "/web/system/models/purge").status_code, 403)
        csrf = login.json()["csrf_token"]
        self.assertEqual(self.browser("POST", "/web/system/models/purge", headers={"X-CSRF-Token": csrf}).status_code, 200)
        self.assertEqual(self.calls, 1)
        before = self.app.openapi().get("servers")
        schema = self.browser("GET", "/web/tts/openapi.json")
        self.assertEqual(schema.status_code, 200)
        self.assertEqual(schema.json()["servers"], [{"url": "/web"}])
        self.assertEqual(self.app.openapi().get("servers"), before)
        self.assertIn("/web/tts/openapi.json", self.browser("GET", "/web/tts/docs").text)

    def test_streaming_body_and_media_type_are_preserved(self):
        self.client.get("/")
        response = self.browser("POST", "/web/tts/stream", json={"text": "Xin chào."})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"firstsecond")
        self.assertIn("audio/mpeg", response.headers["content-type"])
        self.assertIn("no-store", response.headers["cache-control"])

    def test_guest_script_libraries_are_isolated_from_other_guests_and_internal_store(self):
        self.client.get("/")
        other = self.new_client()
        other.get("/")
        created = self.browser("POST", "/web/tts/dialogue-script-folders", json={"name": "Bản thu của tôi"})
        self.assertEqual(created.status_code, 200, created.text)
        identity = created.json()["id"]
        self.assertEqual(len(self.browser("GET", "/web/tts/dialogue-scripts").json()["folders"]), 1)
        self.assertEqual(self.browser("GET", "/web/tts/dialogue-scripts", client=other).json()["folders"], [])
        self.assertEqual(self.client.get("/tts/dialogue-scripts").json()["folders"], [])
        self.assertNotEqual(self.browser("DELETE", "/web/tts/dialogue-script-folders/" + identity, client=other).status_code, 200)
        self.assertEqual(len(self.browser("GET", "/web/tts/dialogue-scripts").json()["folders"]), 1)
        self.assertEqual(self.browser("DELETE", "/web/tts/dialogue-script-folders/" + identity).status_code, 200)
        self.assertEqual(self.browser("GET", "/web/tts/dialogue-scripts").json()["folders"], [])

    def test_browser_session_secret_is_private_and_survives_process_restart(self):
        path = self.root / "web-session.key"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        token = self.sessions.issue()
        self.assertEqual(BrowserSessions(path).verify(token), self.sessions.verify(token))


if __name__ == "__main__":
    unittest.main()
