from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kokorotts.admin_auth import AdminStore
from kokorotts.catalog import model_family_ids
from kokorotts.settings import RuntimeSettingsStore
from kokorotts.standalone_ui.admin import attach_admin

PASSWORD = "Local-admin-test-password-2026"


class FakeRuntime:
    def __init__(self, root: Path):
        self.settings = SimpleNamespace(path=root / "settings.json")
        self.served_model_families = model_family_ids()
        self.purges = 0

    def set_served_model_families(self, families):
        self.served_model_families = RuntimeSettingsStore.validate_served_model_families(families)

    def purge(self):
        self.purges += 1
        return ["cpu"], []


class AdminStoreTests(unittest.TestCase):
    def test_cli_generated_credentials_are_usable_private_and_never_printed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "admin.json"
            result = subprocess.run([sys.executable, "-m", "kokorotts.admin_auth", "create", "--path", str(path), "--generate"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = path.with_name("admin-initial.txt")
            password = next(line.split(": ", 1)[1] for line in output.read_text().splitlines() if line.startswith("Mật khẩu:"))
            self.assertNotIn(password, result.stdout + result.stderr)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertIsNotNone(AdminStore(path).login("admin", password))

    def test_credentials_and_sessions_are_private_and_do_not_store_plaintext_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "admin.json"
            store = AdminStore(path)
            store.create("admin", PASSWORD)
            self.assertIsNone(store.login("unknown", PASSWORD))
            self.assertIsNone(store.login("admin", "wrong-password"))
            token, session = store.login("admin", PASSWORD)
            stored = path.read_text()
            self.assertNotIn(PASSWORD, stored)
            self.assertNotIn(token, stored)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(AdminStore(path).session(token), session)
            with patch("kokorotts.admin_auth.time.time", return_value=session.expires + 1):
                self.assertIsNone(store.session(token))
            store.logout(token)
            self.assertIsNone(store.session(token))

    def test_password_reset_revokes_previously_issued_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AdminStore(Path(directory) / "admin.json")
            store.create("admin", PASSWORD)
            token, _ = store.login("admin", PASSWORD)
            store.create("admin", PASSWORD + "-new", replace=True)
            self.assertIsNone(store.session(token))
            self.assertIsNone(store.login("admin", PASSWORD))
            self.assertIsNotNone(store.login("admin", PASSWORD + "-new"))


class AdminRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.store = AdminStore(root / "admin.json")
        self.store.create("admin", PASSWORD)
        self.runtime = FakeRuntime(root)
        self.legacy_calls = 0
        self.app = FastAPI()

        @self.app.get("/system/settings")
        def legacy_settings():
            return {"ok": True}

        @self.app.post("/system/models/purge")
        @self.app.post("/tts/purge")
        def legacy_purge():
            self.legacy_calls += 1
            return {"ok": True}

        @self.app.post("/tts/generate")
        def speech():
            return {"speech": True}

        attach_admin(self.app, runtime=self.runtime, status_provider=lambda: {"runtime": "CPU", "voices": 173, "loaded_models": []}, store=self.store)
        self.client = TestClient(self.app, base_url="https://giongdoc.test")
        self.addCleanup(self.client.close)

    def login(self):
        response = self.client.post("/admin/api/login", json={"username": "admin", "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    def test_anonymous_access_is_blocked_for_both_new_and_legacy_operator_routes(self):
        response = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")
        for path in ["/admin/api/session", "/admin/api/status", "/admin/api/models", "/system/settings"]:
            self.assertEqual(self.client.get(path).status_code, 401, path)
        for path in ["/admin/api/models/purge", "/system/models/purge", "/tts/purge", "/tts/purge/"]:
            self.assertEqual(self.client.post(path).status_code, 401, path)
        self.assertEqual(self.legacy_calls, 0)
        self.assertEqual(self.runtime.purges, 0)
        self.assertEqual(self.client.post("/tts/generate").status_code, 200)

    def test_login_cookie_and_authenticated_dashboard(self):
        response = self.client.post("/admin/api/login", json={"username": "admin", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"]
        for value in ["__Host-solqi_admin=", "HttpOnly", "Secure", "SameSite=strict", "Path=/"]:
            self.assertIn(value, cookie)
        self.assertNotIn("Domain=", cookie)
        page = self.client.get("/admin")
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-admin-view="dashboard"', page.text)
        self.assertIn("no-store", page.headers["cache-control"])
        self.assertIn("frame-ancestors 'none'", page.headers["content-security-policy"])
        self.assertEqual(self.client.get("/admin/api/status").json()["runtime"], "CPU")
        self.assertNotIn("password", self.client.get("/admin/api/session").json())

    def test_csrf_and_origin_checks_protect_every_mutating_operator_route(self):
        headers = self.login()
        initial = list(self.runtime.served_model_families)
        body = {"model_families": initial[:1]}
        for supplied in [{}, {"X-CSRF-Token": "wrong"}, {**headers, "Origin": "https://evil.test"}, {**headers, "Sec-Fetch-Site": "cross-site"}]:
            self.assertEqual(self.client.put("/admin/api/models", json=body, headers=supplied).status_code, 403)
        self.assertEqual(self.runtime.served_model_families, initial)
        self.assertEqual(self.client.post("/tts/purge").status_code, 403)
        self.assertEqual(self.legacy_calls, 0)
        response = self.client.put("/admin/api/models", json=body, headers={**headers, "Origin": "https://giongdoc.test"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.runtime.served_model_families, initial[:1])
        self.assertEqual(self.client.post("/system/models/purge", headers=headers).status_code, 200)
        self.assertEqual(self.legacy_calls, 1)
        self.assertEqual(self.client.post("/admin/api/models/purge", headers=headers).status_code, 200)
        self.assertEqual(self.runtime.purges, 1)

    def test_invalid_model_selection_does_not_change_the_running_configuration(self):
        headers = self.login()
        initial = list(self.runtime.served_model_families)
        for families, status in [([], 422), (["unknown-model"], 400), ([17], 422)]:
            response = self.client.put("/admin/api/models", json={"model_families": families}, headers=headers)
            self.assertEqual(response.status_code, status)
            self.assertEqual(self.runtime.served_model_families, initial)

    def test_logout_expiry_and_reset_reject_session_replay(self):
        headers = self.login()
        token = self.client.cookies.get("__Host-solqi_admin")
        self.assertEqual(self.client.post("/admin/api/logout", headers=headers).status_code, 200)
        self.client.cookies.set("__Host-solqi_admin", token)
        self.assertEqual(self.client.get("/admin/api/status").status_code, 401)
        self.client.cookies.clear()
        self.login()
        with patch("kokorotts.admin_auth.time.time", return_value=time.time() + 9 * 60 * 60):
            self.assertEqual(self.client.get("/admin/api/status").status_code, 401)
        self.store.create("admin", PASSWORD + "-reset", replace=True)
        self.assertEqual(self.client.get("/admin/api/models").status_code, 401)

    def test_bad_password_login_csrf_payload_limits_and_throttling(self):
        credentials = {"username": "admin", "password": PASSWORD}
        response = self.client.post("/admin/api/login", json=credentials, headers={"Origin": "https://evil.test"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.client.cookies)
        self.assertEqual(self.client.post("/admin/api/login", content="username=admin", headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code, 415)
        self.assertEqual(self.client.post("/admin/api/login", content="x" * 9000, headers={"Content-Type": "application/json"}).status_code, 413)
        for _ in range(6):
            response = self.client.post("/admin/api/login", json={"username": "admin", "password": "wrong-password"})
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.post("/admin/api/login", json=credentials).status_code, 429)

    def test_missing_or_corrupt_credentials_never_enable_an_open_admin(self):
        self.store.path.unlink()
        page = self.client.get("/admin/login")
        self.assertEqual(page.status_code, 200)
        self.assertIn("chưa được thiết lập", page.text)
        self.assertEqual(self.client.post("/admin/api/login", json={"username": "admin", "password": PASSWORD}).status_code, 503)
        self.store.path.write_text("invalid-json")
        self.client.cookies.set("__Host-solqi_admin", "a" * 43)
        self.assertEqual(self.client.get("/admin/api/status").status_code, 503)

    def test_http_login_only_works_from_loopback_for_local_development(self):
        credentials = {"username": "admin", "password": PASSWORD}
        with TestClient(self.app, base_url="http://giongdoc.test") as client:
            self.assertEqual(client.post("/admin/api/login", json=credentials).status_code, 400)
        with TestClient(self.app, base_url="http://localhost:7860", client=("127.0.0.1", 50000)) as client:
            response = client.post("/admin/api/login", json=credentials)
            self.assertEqual(response.status_code, 200)
            self.assertIn("solqi_admin_local=", response.headers["set-cookie"])
            self.assertIn("HttpOnly", response.headers["set-cookie"])


if __name__ == "__main__":
    unittest.main()
