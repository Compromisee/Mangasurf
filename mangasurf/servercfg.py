"""Settings and validation for the LAN server.

Split out from ``server.py`` so the desktop Settings panel, the server's own
window and the command line all enforce the same rule. Duplicating a
validator across three UIs is how one of them ends up accepting a four
character token.

The token lives in ``~/.mangasurf/config.json`` next to every other setting.
Previously it was ``secrets.token_urlsafe(12)`` regenerated on each launch,
which meant the phone had to be re-paired every time the server restarted
and any bookmarked link stopped working. A saved token is also something the
user can choose to be memorable.
"""

import re
import secrets

#: Below this a token is guessable at LAN speed, so it is rejected outright
#: rather than accepted with a warning nobody reads.
MIN_TOKEN_LENGTH = 16

#: Long enough that a generated one is not worth attacking, short enough to
#: retype from a screen if the QR/link route fails.
GENERATED_TOKEN_LENGTH = 24

#: Kept to characters that survive a URL query string untouched, so the
#: printed link never needs percent-encoding and never wraps oddly.
_ALLOWED = re.compile(r"^[A-Za-z0-9._~-]+$")

_ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_token(length=GENERATED_TOKEN_LENGTH):
    """A random token, avoiding characters that are misread when retyped.

    ``l``/``1``/``I`` and ``0``/``O`` are left out: this string gets copied
    off a screen by hand often enough for that to matter.
    """
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def validate_token(token):
    """Return ``(ok, message)`` for a candidate token.

    ``message`` is written for a person, not a log file -- it is shown
    verbatim under the input box in both GUIs.
    """
    token = (token or "").strip()
    if not token:
        return False, "Enter a token, or use Generate."
    if len(token) < MIN_TOKEN_LENGTH:
        return (False,
                f"Too short - {len(token)} characters, minimum is "
                f"{MIN_TOKEN_LENGTH}.")
    if not _ALLOWED.match(token):
        return (False,
                "Use letters, digits, and - . _ ~ only, so the link works "
                "without escaping.")
    return True, "Looks good."


def token_is_valid(token):
    return validate_token(token)[0]


def load_server_settings():
    """Current server settings, generating and saving a token if needed.

    Called by both the server and the Settings panel, so the first time
    either is opened a valid token exists and both agree on it.
    """
    from .config import load_settings, update_settings

    settings = load_settings()
    token = (settings.get("server_token") or "").strip()

    if not token_is_valid(token):
        token = generate_token()
        # Persist immediately: if this only lived in memory the phone would
        # be shown a token the next process would not accept.
        update_settings({"server_token": token})

    try:
        port = int(settings.get("server_port") or 8577)
    except (TypeError, ValueError):
        port = 8577
    if not (1 <= port <= 65535):
        port = 8577

    return {
        "token": token,
        "port": port,
        "verbose": bool(settings.get("server_verbose")),
    }


def save_server_settings(token=None, port=None, verbose=None):
    """Update the stored settings. Returns ``(ok, message, settings)``."""
    from .config import update_settings

    changes = {}
    if token is not None:
        ok, message = validate_token(token)
        if not ok:
            return False, message, load_server_settings()
        changes["server_token"] = token.strip()
    if port is not None:
        try:
            port = int(port)
        except (TypeError, ValueError):
            return False, "Port must be a number.", load_server_settings()
        if not (1024 <= port <= 65535):
            return (False,
                    "Use a port between 1024 and 65535 - lower ones need "
                    "administrator rights.", load_server_settings())
        changes["server_port"] = port
    if verbose is not None:
        changes["server_verbose"] = bool(verbose)

    if changes:
        update_settings(changes)
    return True, "Saved.", load_server_settings()
