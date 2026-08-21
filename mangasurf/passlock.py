"""App passcode lock.

Stores a *verifier* for the passcode at ``~/.mangasurf/lock.json`` -- never the
passcode itself. The verifier is PBKDF2-HMAC-SHA256 over a per-install random
salt, so the stored file cannot be reversed into the original passcode and two
users with the same passcode get different hashes.

Scope, stated plainly: this gates the Mangasurf user interface. It stops someone
casually opening the app and seeing your library. It is **not** disk
encryption -- downloaded files stay readable on disk, and anyone with access to
the machine can read them directly. Treat it as a privacy screen, not a vault.

Optional extras:
    * auto-lock after N minutes idle
    * attempt throttling with an escalating lockout window
    * a recovery key shown once at setup, for when the passcode is forgotten
    * optional "hide covers" blur when locked
"""


if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "mangasurf"

import base64
import hashlib
import json
import os
import secrets
import threading
import time

from .paths import ensure as _ensure_data_dir

#: Created on first use, and populated from a MangaDL install if one
#: exists -- see mangasurf.paths.migrate.
DIR = _ensure_data_dir()
LOCK_PATH = os.path.join(DIR, "lock.json")

_lock = threading.RLock()

ITERATIONS = 240_000          # PBKDF2 rounds; tuned to stay well under a second
SALT_BYTES = 16
KEY_BYTES = 32

MIN_LENGTH = 4
MAX_ATTEMPTS = 5              # before a cooldown kicks in
BASE_COOLDOWN = 30            # seconds, doubles each further failed burst
MAX_COOLDOWN = 15 * 60

DEFAULTS = {
    "enabled": False,
    "salt": "",
    "hash": "",
    "iterations": ITERATIONS,
    "recovery_salt": "",
    "recovery_hash": "",
    "auto_lock_minutes": 0,     # 0 = never auto-lock
    "lock_on_start": True,
    "blur_covers": True,        # blur artwork on the lock screen
    "hint": "",
    "failed": 0,
    "locked_until": 0.0,
    "created": "",
}


# --------------------------------------------------------------- storage


def _load() -> dict:
    try:
        with open(LOCK_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULTS, **data} if isinstance(data, dict) else dict(DEFAULTS)
    except (OSError, ValueError):
        return dict(DEFAULTS)


def _save(data: dict) -> dict:
    os.makedirs(DIR, exist_ok=True)
    tmp = LOCK_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, LOCK_PATH)
    try:                        # best effort: owner-only permissions
        os.chmod(LOCK_PATH, 0o600)
    except OSError:
        pass
    return data


# --------------------------------------------------------------- hashing


def _derive(passcode: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    key = hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), salt,
                              iterations, dklen=KEY_BYTES)
    return base64.b64encode(key).decode("ascii")


def _verify(passcode: str, salt_b64: str, hash_b64: str, iterations: int) -> bool:
    if not salt_b64 or not hash_b64:
        return False
    try:
        salt = base64.b64decode(salt_b64)
    except Exception:
        return False
    candidate = _derive(passcode or "", salt, iterations)
    # constant-time comparison so timing cannot leak the hash
    return secrets.compare_digest(candidate, hash_b64)


def _format_recovery_key(raw: bytes) -> str:
    """Human-transcribable key: 4 groups of 5 unambiguous characters."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no I/O/0/1
    chars = [alphabet[b % len(alphabet)] for b in raw[:20]]
    return "-".join("".join(chars[i:i + 5]) for i in range(0, 20, 5))


# ------------------------------------------------------------------- api


def status() -> dict:
    """Public lock state. Never exposes salts or hashes."""
    with _lock:
        data = _load()
        remaining = max(0.0, float(data.get("locked_until", 0)) - time.time())
        return {
            "enabled": bool(data.get("enabled")),
            "configured": bool(data.get("hash")),
            "auto_lock_minutes": int(data.get("auto_lock_minutes", 0) or 0),
            "lock_on_start": bool(data.get("lock_on_start", True)),
            "blur_covers": bool(data.get("blur_covers", True)),
            "hint": data.get("hint", ""),
            "has_recovery": bool(data.get("recovery_hash")),
            "failed": int(data.get("failed", 0) or 0),
            "cooldown": int(remaining),
            "attempts_left": max(0, MAX_ATTEMPTS - int(data.get("failed", 0) or 0)),
        }


def is_enabled() -> bool:
    return bool(_load().get("enabled"))


def set_passcode(passcode: str, hint: str = "", auto_lock_minutes: int = 0,
                 lock_on_start: bool = True, blur_covers: bool = True) -> dict:
    """Enable the lock. Returns a one-time recovery key -- show it once."""
    passcode = (passcode or "").strip()
    if len(passcode) < MIN_LENGTH:
        return {"ok": False,
                "error": f"Passcode must be at least {MIN_LENGTH} characters"}

    with _lock:
        salt = secrets.token_bytes(SALT_BYTES)
        recovery_raw = secrets.token_bytes(20)
        recovery_key = _format_recovery_key(recovery_raw)
        recovery_salt = secrets.token_bytes(SALT_BYTES)

        _save({
            **_load(),
            "enabled": True,
            "salt": base64.b64encode(salt).decode("ascii"),
            "hash": _derive(passcode, salt),
            "iterations": ITERATIONS,
            "recovery_salt": base64.b64encode(recovery_salt).decode("ascii"),
            "recovery_hash": _derive(recovery_key, recovery_salt),
            "auto_lock_minutes": max(0, int(auto_lock_minutes or 0)),
            "lock_on_start": bool(lock_on_start),
            "blur_covers": bool(blur_covers),
            "hint": (hint or "")[:120],
            "failed": 0,
            "locked_until": 0.0,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        return {"ok": True, "recovery_key": recovery_key}


def change_passcode(current: str, new: str) -> dict:
    with _lock:
        data = _load()
        if data.get("enabled") and not _verify(
                current, data["salt"], data["hash"], data.get("iterations", ITERATIONS)):
            return {"ok": False, "error": "Current passcode is incorrect"}
        new = (new or "").strip()
        if len(new) < MIN_LENGTH:
            return {"ok": False,
                    "error": f"Passcode must be at least {MIN_LENGTH} characters"}
        salt = secrets.token_bytes(SALT_BYTES)
        data.update({"salt": base64.b64encode(salt).decode("ascii"),
                     "hash": _derive(new, salt), "iterations": ITERATIONS,
                     "failed": 0, "locked_until": 0.0})
        _save(data)
        return {"ok": True}


def disable(passcode: str) -> dict:
    """Turn the lock off. Requires the current passcode."""
    with _lock:
        data = _load()
        if not data.get("enabled"):
            return {"ok": True}
        if not _verify(passcode, data["salt"], data["hash"],
                       data.get("iterations", ITERATIONS)):
            return {"ok": False, "error": "Passcode is incorrect"}
        _save({**dict(DEFAULTS), "enabled": False})
        return {"ok": True}


def verify(passcode: str) -> dict:
    """Check a passcode, applying attempt throttling."""
    with _lock:
        data = _load()
        if not data.get("enabled"):
            return {"ok": True}

        now = time.time()
        locked_until = float(data.get("locked_until", 0) or 0)
        if locked_until > now:
            return {"ok": False, "error": "Too many attempts",
                    "cooldown": int(locked_until - now)}

        if _verify(passcode, data["salt"], data["hash"],
                   data.get("iterations", ITERATIONS)):
            data.update({"failed": 0, "locked_until": 0.0})
            _save(data)
            return {"ok": True}

        failed = int(data.get("failed", 0) or 0) + 1
        data["failed"] = failed
        if failed >= MAX_ATTEMPTS:
            bursts = failed // MAX_ATTEMPTS
            cooldown = min(MAX_COOLDOWN, BASE_COOLDOWN * (2 ** (bursts - 1)))
            data["locked_until"] = now + cooldown
            _save(data)
            return {"ok": False, "error": "Too many attempts",
                    "cooldown": int(cooldown)}
        _save(data)
        return {"ok": False, "error": "Incorrect passcode",
                "attempts_left": MAX_ATTEMPTS - failed}


def recover(recovery_key: str, new_passcode: str) -> dict:
    """Reset the passcode using the recovery key issued at setup."""
    with _lock:
        data = _load()
        key = (recovery_key or "").strip().upper().replace(" ", "")
        if not data.get("recovery_hash"):
            return {"ok": False, "error": "No recovery key is configured"}
        if not _verify(key, data.get("recovery_salt", ""),
                       data.get("recovery_hash", ""),
                       data.get("iterations", ITERATIONS)):
            return {"ok": False, "error": "Recovery key is incorrect"}

        new_passcode = (new_passcode or "").strip()
        if len(new_passcode) < MIN_LENGTH:
            return {"ok": False,
                    "error": f"Passcode must be at least {MIN_LENGTH} characters"}

        salt = secrets.token_bytes(SALT_BYTES)
        data.update({"salt": base64.b64encode(salt).decode("ascii"),
                     "hash": _derive(new_passcode, salt),
                     "failed": 0, "locked_until": 0.0})
        _save(data)
        return {"ok": True}


def update_options(**changes) -> dict:
    """Change lock behaviour (auto-lock, blur, hint) without the passcode."""
    allowed = {"auto_lock_minutes", "lock_on_start", "blur_covers", "hint"}
    with _lock:
        data = _load()
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key == "auto_lock_minutes":
                data[key] = max(0, int(value or 0))
            elif key == "hint":
                data[key] = (value or "")[:120]
            else:
                data[key] = bool(value)
        _save(data)
        return status()
