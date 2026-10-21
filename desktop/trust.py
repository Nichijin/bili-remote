import hmac
import json
import os
import secrets
import socket
import uuid
from pathlib import Path
from .windows import data_directory


class TrustStore:
    """The public device ID identifies a record; only its secret authenticates it."""
    def __init__(self, path=None):
        self.path = Path(path) if path else data_directory() / "trust.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {"computer_id": str(uuid.uuid4()), "devices": {}}
        self.data.setdefault("computer_id", str(uuid.uuid4()))
        self.data.setdefault("devices", {})
        self.save()

    @property
    def computer_id(self):
        return self.data["computer_id"]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def authenticate(self, device_id, token):
        known = self.data["devices"].get(device_id)
        return bool(known and isinstance(token, str) and hmac.compare_digest(known["token"].encode(), token.encode()))

    def allow(self, device_id, name):
        token = secrets.token_urlsafe(32)
        self.data["devices"][device_id] = {"name": name, "token": token}
        self.save()
        return token

    def revoke_all(self):
        self.data["devices"] = {}
        self.save()

    def public_info(self, port):
        return {"kind": "bili_remote_computer", "version": 1, "computer_id": self.computer_id, "name": socket.gethostname(), "port": port}
