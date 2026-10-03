"""Regression guards for demo device identity and browser cache safety."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEVICE_CLIENTS = ("waiting_room", "room_display", "totem")


def test_device_clients_never_default_to_device_one():
    """Missing device ids must fail closed instead of silently selecting id 1."""
    for client in DEVICE_CLIENTS:
        source = (ROOT / "dev" / "demo_clients" / client / "app.js").read_text()
        assert 'queryInt("id", 1)' not in source
        assert 'queryInt("id")' in source
        assert "Missing or invalid" in source


def test_device_client_scripts_use_cache_busting_urls():
    """A changed device script must not reuse a pre-fix browser cache entry."""
    for client in DEVICE_CLIENTS:
        html = (ROOT / "dev" / "demo_clients" / client / "index.html").read_text()
        assert 'src="app.js?v=' in html


def test_demo_gateway_disables_browser_caching():
    config = (ROOT / "dev" / "demo_web" / "nginx.conf").read_text()
    assert 'Cache-Control "no-store, max-age=0, must-revalidate"' in config
    assert 'Pragma "no-cache"' in config
    assert 'Expires "0"' in config
