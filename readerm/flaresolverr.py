"""Optional FlareSolverr client used as a fallback when Cloudflare blocks direct requests."""

import json
import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:8191/v1"
DEFAULT_TIMEOUT_MS = 60000


class FlareSolverrSession:
    """Persistent FlareSolverr session wrapper.

    Reuses the same Cloudflare session id so the challenge is only solved once.
    """

    def __init__(self, timeout: int = DEFAULT_TIMEOUT_MS, url: str = DEFAULT_URL):
        self.timeout = timeout
        self.url = url
        self._session_id: Optional[str] = None
        self._last_used = 0.0

    def create_session(self) -> Optional[str]:
        try:
            resp = requests.post(self.url, json={"cmd": "sessions.create"}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "ok":
                self._session_id = data["session"]
                self._last_used = time.time()
                logger.info("Created FlareSolverr session: %s", self._session_id)
                return self._session_id
            logger.error("FlareSolverr session creation failed: %s", data.get("message"))
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error("Could not connect to FlareSolverr at %s: %s", self.url, e)
            logger.info("Start it with: python start_flaresolverr.py")
            return None
        except requests.exceptions.RequestException as e:
            logger.error("Request to FlareSolverr failed: %s", e)
            return None

    def destroy_session(self) -> None:
        if self._session_id:
            try:
                requests.post(
                    self.url,
                    json={"cmd": "sessions.destroy", "session": self._session_id},
                    timeout=10,
                )
            except Exception as e:
                logger.warning("Failed to destroy session %s: %s", self._session_id, e)
            finally:
                self._session_id = None

    def get(self, url: str, **kwargs):
        """GET a page through FlareSolverr; returns a requests.Response-like object."""
        if not self._session_id and not self.create_session():
            raise ConnectionError(
                "FlareSolverr is not running. Quick start: python start_flaresolverr.py"
            )

        payload = {
            "cmd": "request.get",
            "url": url,
            "session": self._session_id,
            "maxTimeout": self.timeout,
        }
        request_timeout = kwargs.get("timeout", 120)

        try:
            resp = requests.post(self.url, json=payload, timeout=request_timeout)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "ok":
                msg = str(data.get("message", "")).lower()
                if "session" in msg and ("not exist" in msg or "not found" in msg):
                    logger.warning("FlareSolverr session invalid, recreating...")
                    self._session_id = None
                    if self.create_session():
                        payload["session"] = self._session_id
                        resp = requests.post(self.url, json=payload, timeout=request_timeout)
                        resp.raise_for_status()
                        data = resp.json()
                if data.get("status") != "ok":
                    raise ConnectionError(f"FlareSolverr error: {data.get('message', 'unknown')}")

            self._last_used = time.time()
            return FakeSolverrResponse(data["solution"])

        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(
                f"FlareSolverr is not reachable at {self.url}. "
                f"Confirm it is running on port 8191. Error: {e}"
            )
        except requests.exceptions.Timeout:
            raise TimeoutError(
                f"FlareSolverr request timed out after {request_timeout}s."
            )


class FakeSolverrResponse:
    """Mimics requests.Response using FlareSolverr output."""

    def __init__(self, solution: dict):
        self.text = solution.get("response", "")
        self.content = self.text.encode("utf-8") if isinstance(self.text, str) else self.text
        self.status_code = solution.get("status", 200)
        self.url = solution.get("url", "")
        self.ok = 200 <= self.status_code < 400
        self.headers = solution.get("headers", {})
        self.reason = solution.get("statusText", "")
        self.cookies = {}
        for cookie in solution.get("cookies", []) or []:
            if isinstance(cookie, dict) and "name" in cookie:
                self.cookies[cookie["name"]] = cookie.get("value", "")

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(
                f"{self.status_code} {self.reason or 'Error'} for url: {self.url}",
                response=self,
            )

    def json(self):
        if not self.text:
            raise ValueError("No JSON content to parse")
        return json.loads(self.text)


def is_flaresolverr_running(url: str = DEFAULT_URL) -> bool:
    try:
        health = url.replace("/v1", "") + "/health"
        return requests.get(health, timeout=2).status_code == 200
    except requests.exceptions.RequestException:
        return False
