"""Device and client tracking for Mangasurf LAN Web Server and OPDS Catalog.

Keeps an in-memory, thread-safe registry of connected phones, tablets,
desktop browsers, e-readers, and OPDS clients accessing Mangasurf.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional


def parse_device_info(user_agent: str, ip: str, service: str = "web") -> Dict[str, Any]:
    """Parse User-Agent string to extract friendly device name, OS, browser,

    device type, and Material Symbols icon name.
    """
    ua = (user_agent or "").strip()
    ua_lower = ua.lower()

    if not ua:
        return {
            "name": f"Device ({ip})",
            "type": "mobile" if service == "web" else "ereader",
            "os": "Unknown",
            "browser": "Unknown",
            "icon": "smartphone" if service == "web" else "menu_book",
        }

    # 1. Specialized OPDS Clients & Reader Apps
    if "readest" in ua_lower:
        os_n = "iOS/iPadOS" if any(x in ua_lower for x in ("darwin", "cfnetwork", "iphone", "ipad")) else "Mobile"
        return {
            "name": "Readest OPDS Reader",
            "type": "ereader",
            "os": os_n,
            "browser": "Readest",
            "icon": "menu_book",
        }
    if "panels" in ua_lower:
        return {
            "name": "Panels Comic Reader",
            "type": "tablet" if "ipad" in ua_lower else "mobile",
            "os": "iOS/iPadOS",
            "browser": "Panels",
            "icon": "menu_book",
        }
    if "kybook" in ua_lower:
        return {
            "name": "KyBook 3 Reader",
            "type": "ereader",
            "os": "iOS",
            "browser": "KyBook",
            "icon": "menu_book",
        }
    if "chunky" in ua_lower:
        return {
            "name": "Chunky Comic Reader",
            "type": "tablet",
            "os": "iPadOS",
            "browser": "Chunky",
            "icon": "tablet_mac",
        }
    if "aldiko" in ua_lower:
        return {
            "name": "Aldiko Book Reader",
            "type": "ereader",
            "os": "Android",
            "browser": "Aldiko",
            "icon": "menu_book",
        }
    if "tachiyomi" in ua_lower or "mihon" in ua_lower:
        return {
            "name": "Mihon / Tachiyomi",
            "type": "mobile",
            "os": "Android",
            "browser": "Mihon",
            "icon": "smartphone",
        }
    if "kobo" in ua_lower:
        return {
            "name": "Kobo eReader",
            "type": "ereader",
            "os": "Linux",
            "browser": "Kobo",
            "icon": "menu_book",
        }
    if "thorium" in ua_lower:
        return {
            "name": "Thorium Reader",
            "type": "desktop",
            "os": "Desktop",
            "browser": "Thorium",
            "icon": "menu_book",
        }

    # 2. Operating System & Form Factor
    os_name = "Unknown OS"
    dev_type = "desktop"
    icon = "laptop"

    if "ipad" in ua_lower:
        os_name = "iPadOS"
        dev_type = "tablet"
        icon = "tablet_mac"
    elif "iphone" in ua_lower:
        os_name = "iOS"
        dev_type = "mobile"
        icon = "smartphone"
    elif "android" in ua_lower:
        os_name = "Android"
        if any(t in ua_lower for t in ("tablet", "nexus 9", "sm-t", "tab")):
            dev_type = "tablet"
            icon = "tablet_android"
        else:
            dev_type = "mobile"
            icon = "smartphone"
    elif "windows nt" in ua_lower or "windows" in ua_lower:
        os_name = "Windows"
        dev_type = "desktop"
        icon = "desktop_windows"
    elif "macintosh" in ua_lower or "mac os x" in ua_lower:
        os_name = "macOS"
        dev_type = "desktop"
        icon = "laptop_mac"
    elif "cros" in ua_lower:
        os_name = "ChromeOS"
        dev_type = "desktop"
        icon = "laptop"
    elif "linux" in ua_lower:
        os_name = "Linux"
        dev_type = "desktop"
        icon = "computer"

    # 3. Browser detection
    browser = "Browser"
    if "edg/" in ua_lower or "edge/" in ua_lower:
        browser = "Edge"
    elif "opr/" in ua_lower or "opera" in ua_lower:
        browser = "Opera"
    elif "chrome" in ua_lower and "safari" in ua_lower and "edg" not in ua_lower:
        browser = "Chrome"
    elif "firefox" in ua_lower or "fxios" in ua_lower:
        browser = "Firefox"
    elif "safari" in ua_lower and "chrome" not in ua_lower:
        browser = "Safari"
    elif "curl" in ua_lower:
        browser = "curl"
        icon = "terminal"
    elif "python" in ua_lower:
        browser = "Python Client"
        icon = "terminal"

    # 4. Model extraction
    model = ""
    if "iphone" in ua_lower:
        model = "Apple iPhone"
    elif "ipad" in ua_lower:
        model = "Apple iPad"
    elif "android" in ua_lower:
        match = re.search(r"Android[^;]+;(?:\s*wv\s*;)?\s*([^;)]+)\s*Build", ua)
        if match:
            raw_model = match.group(1).strip()
            raw_model = re.sub(r"^(samsung|google|xiaomi|huawei|oneplus|motorola|oppo|vivo)\s+", "", raw_model, flags=re.I)
            if raw_model:
                model = raw_model
        if not model:
            model = "Android Phone" if dev_type == "mobile" else "Android Tablet"

    if model:
        name = f"{model} ({browser})"
    elif os_name != "Unknown OS":
        name = f"{os_name} ({browser})"
    else:
        name = f"{browser} ({ip})"

    return {
        "name": name,
        "type": dev_type,
        "os": os_name,
        "browser": browser,
        "icon": icon,
    }


class DeviceTracker:
    """Thread-safe device tracking registry for LAN and OPDS servers."""

    def __init__(self, max_devices: int = 100):
        self._devices: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._max_devices = max_devices

    def _is_tailscale(self, ip: str) -> bool:
        if not ip or not str(ip).startswith("100."):
            return False
        parts = str(ip).split(".")
        if len(parts) == 4 and parts[0] == "100" and parts[1].isdigit():
            return 64 <= int(parts[1]) <= 127
        return False

    def record_request(
        self,
        ip: str,
        user_agent: str = "",
        service: str = "web",
        endpoint: str = "",
        bytes_transferred: int = 0,
    ) -> Dict[str, Any]:
        """Record an incoming HTTP request from a client device."""
        ip = (ip or "127.0.0.1").strip()
        now = time.time()
        key = f"{ip}"

        with self._lock:
            if key in self._devices:
                dev = self._devices[key]
                dev["last_seen"] = now
                dev["requests_count"] += 1
                dev["bytes_transferred"] = dev.get("bytes_transferred", 0) + max(0, bytes_transferred)
                if endpoint:
                    dev["last_endpoint"] = endpoint
                if user_agent and (not dev.get("user_agent") or len(user_agent) > len(dev.get("user_agent", ""))):
                    parsed = parse_device_info(user_agent, ip, service=service)
                    dev.update({
                        "name": parsed["name"],
                        "type": parsed["type"],
                        "os": parsed["os"],
                        "browser": parsed["browser"],
                        "icon": parsed["icon"],
                        "user_agent": user_agent,
                    })
                # If seen on both services
                if dev.get("service_id") != service:
                    dev["service_id"] = "both"
                    dev["service"] = "Web & OPDS"
                return dict(dev)

            # New device
            parsed = parse_device_info(user_agent, ip, service=service)
            is_ts = self._is_tailscale(ip)
            is_local = ip in ("127.0.0.1", "localhost", "::1")
            
            service_label = "LAN Web Reader" if service == "web" else "OPDS Catalog"

            device_info = {
                "id": key,
                "ip": ip,
                "name": parsed["name"],
                "type": parsed["type"],
                "os": parsed["os"],
                "browser": parsed["browser"],
                "icon": parsed["icon"],
                "user_agent": user_agent or "",
                "service": service_label,
                "service_id": service,
                "is_tailscale": is_ts,
                "is_localhost": is_local,
                "first_seen": now,
                "last_seen": now,
                "requests_count": 1,
                "bytes_transferred": max(0, bytes_transferred),
                "last_endpoint": endpoint or "/",
            }

            # Enforce max devices capacity
            if len(self._devices) >= self._max_devices:
                # Evict oldest device
                oldest_key = min(self._devices, key=lambda k: self._devices[k]["last_seen"])
                self._devices.pop(oldest_key, None)

            self._devices[key] = device_info
            return dict(device_info)

    def get_devices(
        self,
        service: Optional[str] = None,
        active_only: bool = False,
        active_threshold: float = 120.0,
    ) -> List[Dict[str, Any]]:
        """Return a sorted list of registered devices formatted for JSON."""
        now = time.time()
        results = []

        with self._lock:
            items = list(self._devices.values())

        for d in items:
            if service and d["service_id"] not in (service, "both"):
                continue

            idle_secs = max(0.0, now - d["last_seen"])
            is_active = idle_secs <= active_threshold

            if active_only and not is_active:
                continue

            # Determine human-friendly status label
            if idle_secs < 15:
                status = "active"
                status_label = "Active now"
            elif idle_secs < 60:
                status = "active"
                status_label = f"{int(idle_secs)}s ago"
            elif idle_secs < 3600:
                mins = int(idle_secs // 60)
                status = "active" if mins < 5 else "idle"
                status_label = f"{mins}m ago"
            elif idle_secs < 86400:
                hrs = int(idle_secs // 3600)
                status = "offline"
                status_label = f"{hrs}h ago"
            else:
                days = int(idle_secs // 86400)
                status = "offline"
                status_label = f"{days}d ago"

            # Format transferred bytes
            raw_bytes = d.get("bytes_transferred", 0)
            if raw_bytes >= 1024 * 1024 * 1024:
                size_str = f"{raw_bytes / (1024 * 1024 * 1024):.1f} GB"
            elif raw_bytes >= 1024 * 1024:
                size_str = f"{raw_bytes / (1024 * 1024):.1f} MB"
            elif raw_bytes >= 1024:
                size_str = f"{raw_bytes / 1024:.0f} KB"
            else:
                size_str = f"{raw_bytes} B"

            first_seen_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(d["first_seen"]))
            last_seen_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(d["last_seen"]))

            results.append({
                **d,
                "status": status,
                "status_label": status_label,
                "is_active": is_active,
                "idle_seconds": int(idle_secs),
                "first_seen_formatted": first_seen_str,
                "last_seen_formatted": last_seen_str,
                "data_transferred": size_str,
            })

        # Sort newest/active first
        results.sort(key=lambda x: (-1 if x["is_active"] else 0, -x["last_seen"]))
        return results

    def active_count(self, service: Optional[str] = None, active_threshold: float = 120.0) -> int:
        """Count devices active within the given threshold in seconds."""
        now = time.time()
        with self._lock:
            count = 0
            for d in self._devices.values():
                if service and d["service_id"] not in (service, "both"):
                    continue
                if (now - d["last_seen"]) <= active_threshold:
                    count += 1
            return count

    def total_count(self, service: Optional[str] = None) -> int:
        with self._lock:
            if not service:
                return len(self._devices)
            return sum(1 for d in self._devices.values() if d["service_id"] in (service, "both"))

    def clear_inactive(self, max_idle: float = 900.0) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            keys_to_remove = [k for k, v in self._devices.items() if (now - v["last_seen"]) > max_idle]
            for k in keys_to_remove:
                del self._devices[k]
                removed += 1
        return removed

    def clear_all(self) -> None:
        with self._lock:
            self._devices.clear()


# Global singleton instance shared across servers
tracker = DeviceTracker()
