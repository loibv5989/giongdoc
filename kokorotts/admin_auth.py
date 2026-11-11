"""Single administrator credentials and revocable file-backed sessions."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from filelock import FileLock

SESSION_SECONDS = 8 * 60 * 60
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
MAX_SESSIONS = 8


class AdminStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdminSession:
    username: str
    csrf_token: str
    expires: int


def default_admin_path() -> Path:
    configured = os.getenv("KOKOROTTS_ADMIN_PATH")
    if configured:
        return Path(configured)
    settings = os.getenv("KOKOROTTS_SETTINGS_PATH", "/app/persistent/app/settings.json")
    return Path(settings).with_name("admin.json")


def password_hash(password: str) -> str:
    if not 12 <= len(password) <= 1024:
        raise ValueError("Mật khẩu phải có từ 12 đến 1024 ký tự.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=256 * 1024 * 1024)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def check_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n_text, r_text, p_text, salt, expected = encoded.split("$")
        parameters = (int(n_text), int(r_text), int(p_text))
        salt_bytes = base64.b64decode(salt, validate=True)
        expected_bytes = base64.b64decode(expected, validate=True)
        if algorithm != "scrypt" or parameters not in {(2**17, 8, 1), (2**16, 8, 2), (2**15, 8, 3)}:
            return False
        if len(salt_bytes) != 16 or len(expected_bytes) != 64 or len(password) > 1024:
            return False
        n, r, p = parameters
        actual = hashlib.scrypt(password.encode(), salt=salt_bytes, n=n, r=r, p=p, maxmem=256 * 1024 * 1024)
        return hmac.compare_digest(actual, expected_bytes)
    except (ValueError, TypeError):
        return False


class AdminStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._password_lock = Lock()

    @property
    def configured(self) -> bool:
        return self.path.is_file()

    def _lock(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self.path) + ".lock", timeout=10)

    def _read(self) -> dict:
        try:
            record = json.loads(self.path.read_text(encoding="utf-8"))
            if record.get("schema_version") != 1 or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", record["username"]):
                raise ValueError("Invalid administrator record")
            if not isinstance(record["password"], str) or not re.fullmatch(r"[0-9a-f]{64}", record["csrf_key"]):
                raise ValueError("Invalid administrator credentials")
            if not isinstance(record["sessions"], dict) or len(record["sessions"]) > MAX_SESSIONS:
                raise ValueError("Invalid administrator sessions")
            return record
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise AdminStorageError("Không đọc được tài khoản quản trị.") from exc

    def _write(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".admin-", suffix=".tmp", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def create(self, username: str, password: str, *, replace: bool = False) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
            raise ValueError("Tên đăng nhập chỉ gồm chữ, số, dấu chấm, gạch dưới hoặc gạch ngang; tối đa 64 ký tự.")
        encoded = password_hash(password)
        with self._lock():
            if self.path.exists() and not replace:
                raise ValueError("Tài khoản quản trị đã được tạo.")
            self._write({"schema_version": 1, "username": username, "password": encoded, "csrf_key": secrets.token_hex(32), "sessions": {}})

    @staticmethod
    def _session(record: dict, token: str, expires: int) -> AdminSession:
        csrf = hmac.new(bytes.fromhex(record["csrf_key"]), token.encode(), hashlib.sha256).hexdigest()
        return AdminSession(record["username"], csrf, expires)

    def login(self, username: str, password: str) -> tuple[str, AdminSession] | None:
        with self._password_lock:
            with self._lock():
                record = self._read()
            valid_password = check_password(password, record["password"])
            if not valid_password or not hmac.compare_digest(username.encode(), record["username"].encode()):
                return None
            with self._lock():
                latest = self._read()
                if latest["password"] != record["password"] or latest["csrf_key"] != record["csrf_key"]:
                    return None
                now = int(time.time())
                sessions = {key: value for key, value in latest["sessions"].items() if isinstance(value, int) and value > now}
                while len(sessions) >= MAX_SESSIONS:
                    del sessions[min(sessions, key=sessions.get)]
                token = secrets.token_urlsafe(32)
                expires = now + SESSION_SECONDS
                sessions[hashlib.sha256(token.encode()).hexdigest()] = expires
                latest["sessions"] = sessions
                self._write(latest)
                return token, self._session(latest, token, expires)

    def session(self, token: str | None) -> AdminSession | None:
        if not token or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token) or not self.configured:
            return None
        with self._lock():
            record = self._read()
        expires = record["sessions"].get(hashlib.sha256(token.encode()).hexdigest())
        if not isinstance(expires, int) or expires <= time.time():
            return None
        return self._session(record, token, expires)

    def logout(self, token: str) -> None:
        with self._lock():
            record = self._read()
            record["sessions"].pop(hashlib.sha256(token.encode()).hexdigest(), None)
            self._write(record)


class LoginThrottle:
    def __init__(self):
        self._lock = Lock()
        self._global: deque[float] = deque()
        self._clients: dict[str, deque[float]] = {}

    def allow(self, client: str) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._global and self._global[0] <= now - 60:
                self._global.popleft()
            self._clients = {key: queue for key, queue in self._clients.items() if queue and queue[-1] > now - 300}
            if client not in self._clients and len(self._clients) >= 1024:
                return False
            queue = self._clients.setdefault(client, deque())
            while queue and queue[0] <= now - 300:
                queue.popleft()
            if len(queue) >= 8 or len(self._global) >= 30:
                return False
            queue.append(now)
            self._global.append(now)
            return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Tạo hoặc đặt lại tài khoản quản trị SolQi-TTS.")
    parser.add_argument("action", choices=["create", "reset"])
    parser.add_argument("--username", default="admin")
    parser.add_argument("--path", type=Path, default=default_admin_path())
    parser.add_argument("--generate", action="store_true", help="Lưu mật khẩu ngẫu nhiên vào file admin-initial.txt cạnh file tài khoản.")
    args = parser.parse_args()
    store = AdminStore(args.path)
    if store.configured and args.action == "create":
        parser.error("Tài khoản đã tồn tại; dùng reset để đặt lại mật khẩu.")
    if not store.configured and args.action == "reset":
        parser.error("Chưa có tài khoản quản trị.")
    output = args.path.with_name("admin-initial.txt")
    if args.generate and output.exists():
        parser.error("File admin-initial.txt đã tồn tại; hãy cất file đó trước khi tạo mật khẩu mới.")
    password = secrets.token_urlsafe(24) if args.generate else getpass.getpass("Mật khẩu: ")
    if not args.generate and password != getpass.getpass("Nhập lại mật khẩu: "):
        parser.error("Mật khẩu nhập lại không khớp.")
    try:
        store.create(args.username, password, replace=args.action == "reset")
        if args.generate:
            with open(output, "x", encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
                handle.write(f"Trang quản trị: /admin\nTên đăng nhập: {args.username}\nMật khẩu: {password}\n")
            print(f"Thông tin đăng nhập đã lưu tại {output}")
        else:
            print("Đã lưu tài khoản quản trị. Các phiên đăng nhập cũ đã được thu hồi.")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
