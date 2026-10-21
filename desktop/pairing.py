import hmac
import secrets
import time


class PairingCode:
    """Short-lived first-use PIN; subsequent connections use per-device secrets."""
    def __init__(self, lifetime=600):
        self.lifetime = lifetime
        self.rotate()

    def rotate(self):
        self.code = f"{secrets.randbelow(1_000_000):06d}"
        self.deadline = time.monotonic() + self.lifetime
        return self.code

    def current(self):
        if time.monotonic() >= self.deadline:
            self.rotate()
        return self.code

    def verify(self, candidate):
        return isinstance(candidate, str) and len(candidate) == 6 and candidate.isascii() and candidate.isdigit() and hmac.compare_digest(candidate, self.current())
