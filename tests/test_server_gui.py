"""Tests for GUI Server & OPDS management, live status updates, and device tracking."""

import time
import pytest
from mangasurf.devices import DeviceTracker, parse_device_info, tracker
from mangasurf.gui import Api
from mangasurf.config import load_settings, update_settings


def test_device_info_parsing():
    """Verify user agents are accurately parsed into names, types, OS, and icons."""
    # 1. iPhone Safari
    ua_ios = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
    info_ios = parse_device_info(ua_ios, "192.168.1.101", service="web")
    assert info_ios["type"] == "mobile"
    assert info_ios["os"] == "iOS"
    assert info_ios["browser"] == "Safari"
    assert info_ios["icon"] == "smartphone"
    assert "iPhone" in info_ios["name"]

    # 2. iPad Safari
    ua_ipad = "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
    info_ipad = parse_device_info(ua_ipad, "192.168.1.102", service="web")
    assert info_ipad["type"] == "tablet"
    assert info_ipad["os"] == "iPadOS"
    assert info_ipad["icon"] == "tablet_mac"

    # 3. Android Chrome (Google Pixel)
    ua_android = "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/UQ1A.240205.004) AppleWebKit/537.36 Chrome/124.0.0.0 Mobile Safari/537.36"
    info_android = parse_device_info(ua_android, "192.168.1.103", service="web")
    assert info_android["type"] == "mobile"
    assert info_android["os"] == "Android"
    assert info_android["browser"] == "Chrome"
    assert "Pixel" in info_android["name"]

    # 4. Readest OPDS App
    ua_readest = "Readest/2.4.1 CFNetwork/1410.0.3 Darwin/22.4.0"
    info_readest = parse_device_info(ua_readest, "192.168.1.104", service="opds")
    assert info_readest["name"] == "Readest OPDS Reader"
    assert info_readest["type"] == "ereader"
    assert info_readest["icon"] == "menu_book"

    # 5. Panels Comic Reader
    ua_panels = "Panels/3.0.0 (iPad; iOS 17.2)"
    info_panels = parse_device_info(ua_panels, "192.168.1.105", service="opds")
    assert info_panels["name"] == "Panels Comic Reader"
    assert info_panels["type"] == "tablet"

    # 6. Windows PC Desktop Chrome
    ua_win = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    info_win = parse_device_info(ua_win, "127.0.0.1", service="web")
    assert info_win["type"] == "desktop"
    assert info_win["os"] == "Windows"
    assert info_win["browser"] == "Chrome"


def test_device_tracker_lifecycle():
    """Test recording requests, calculating activity status, byte tracking, and pruning."""
    test_tracker = DeviceTracker()

    # Record first request from iPhone
    d1 = test_tracker.record_request(
        ip="192.168.1.50",
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1",
        service="web",
        endpoint="/stream/page",
        bytes_transferred=2048576,
    )
    assert d1["ip"] == "192.168.1.50"
    assert d1["requests_count"] == 1
    assert d1["bytes_transferred"] == 2048576

    # Record second request from same device
    d1_again = test_tracker.record_request(
        ip="192.168.1.50",
        service="web",
        endpoint="/api/search",
        bytes_transferred=1024,
    )
    assert d1_again["requests_count"] == 2
    assert d1_again["bytes_transferred"] == 2049600

    # Record request from OPDS client
    test_tracker.record_request(
        ip="192.168.1.60",
        user_agent="Readest/2.4.1",
        service="opds",
        endpoint="/opds/all",
        bytes_transferred=512000,
    )

    # Check active counts
    assert test_tracker.active_count() == 2
    assert test_tracker.active_count(service="web") == 1
    assert test_tracker.active_count(service="opds") == 1
    assert test_tracker.total_count() == 2

    # Verify device list format
    devices = test_tracker.get_devices()
    assert len(devices) == 2
    assert any(d["status"] == "active" for d in devices)
    assert any(d["is_active"] is True for d in devices)

    # Test clear all
    test_tracker.clear_all()
    assert test_tracker.total_count() == 0


def test_gui_api_servers_status_and_lifecycle():
    """Test start, stop, restart, and status reporting for LAN Server and OPDS in GUI Api."""
    api = Api()

    # Initial status: offline
    status = api.get_servers_status()
    assert status["ok"] is True
    assert "server" in status
    assert "opds" in status
    assert status["server"]["running"] is False
    assert status["opds"]["running"] is False

    # Start LAN Server on a test port
    start_res = api.start_server(port=9281)
    assert start_res["ok"] is True
    assert start_res["running"] is True
    assert start_res["port"] == 9281
    assert "url" in start_res
    assert "localhost:9281" in start_res["local_url"]

    # Check updated servers status
    status2 = api.get_servers_status()
    assert status2["server"]["running"] is True
    assert status2["any_running"] is True
    assert status2["opds"]["running"] is False

    # Start OPDS Server on a test port
    start_opds_res = api.start_opds(port=9282)
    assert start_opds_res["ok"] is True
    assert start_opds_res["running"] is True
    assert start_opds_res["port"] == 9282
    assert "localhost:9282/opds" in start_opds_res["local_url"]

    # Check both running status
    status3 = api.get_servers_status()
    assert status3["server"]["running"] is True
    assert status3["opds"]["running"] is True
    assert status3["both_running"] is True

    # Stop LAN server
    stop_res = api.stop_server()
    assert stop_res["ok"] is True
    assert stop_res["running"] is False
    assert api.get_servers_status()["server"]["running"] is False

    # Stop OPDS server
    stop_opds_res = api.stop_opds()
    assert stop_opds_res["ok"] is True
    assert stop_opds_res["running"] is False
    assert api.get_servers_status()["opds"]["running"] is False


def test_gui_api_server_settings():
    """Test updating server configurations, autostart options, and token generation."""
    api = Api()

    # Generate new token
    gen_res = api.generate_server_token()
    assert gen_res["ok"] is True
    assert len(gen_res["token"]) >= 16

    # Update server port and autostart
    set_res = api.set_server_config(port=8899, autostart=True, verbose=True)
    assert set_res["ok"] is True
    assert set_res["port"] == 8899
    assert set_res["autostart"] is True
    assert set_res["verbose"] is True

    # Update OPDS port and autostart
    set_opds_res = api.set_opds_config(port=8898, autostart=True)
    assert set_opds_res["ok"] is True
    assert set_opds_res["port"] == 8898
    assert set_opds_res["autostart"] is True

    # Reset test settings to standard defaults
    api.set_server_config(port=8577, autostart=False, verbose=False)
    api.set_opds_config(port=8578, autostart=False)


def test_server_device_apis():
    """Test get_server_devices, clear_server_devices, and get_server_logs endpoints."""
    api = Api()

    # Record dummy device in shared tracker
    tracker.record_request(
        ip="192.168.1.99",
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/604.1",
        service="web",
        endpoint="/stream/page",
    )

    devs_res = api.get_server_devices()
    assert devs_res["ok"] is True
    assert len(devs_res["devices"]) >= 1
    assert devs_res["active_count"] >= 1

    # Clear devices
    clear_res = api.clear_server_devices(inactive_only=False)
    assert clear_res["ok"] is True
    assert len(clear_res["devices"]) == 0

    # Get server logs
    logs_res = api.get_server_logs(service="all")
    assert logs_res["ok"] is True
    assert "lines" in logs_res
