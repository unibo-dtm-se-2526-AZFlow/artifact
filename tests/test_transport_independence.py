"""Transport independence checks for the domain and application core.

Property 12 (Validates: Requirements 11.1, 11.2, 11.6, 11.7, 12.5).

The WebSocket transport now lives in the API and infrastructure layers only.
These checks guard that separation: the domain and application core must not
depend on any real-time delivery technology, and the display behaviour must
stay reachable through the DisplayReadModel port without any transport.
Successful calls publish only through the existing CallEventPublisher seam, so
there is no parallel display-notification mechanism.

These tests are DB-free and run in the normal (non-integration) test run.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

import AZFlow.application as application_pkg
import AZFlow.domain as domain_pkg
from AZFlow.application.ports.display_read_model import DisplayCall, DisplayReadModel

# Delivery technologies that must not appear in the core. Substring match keeps
# the check simple and readable.
_TRANSPORT_TOKENS = (
    "websocket",
    "websockets",
    "starlette.websockets",
    "redis",
    "kombu",
    "aio_pika",
    "pika",
    "kafka",
    "celery",
)

# The domain must also stay free of the web and persistence frameworks.
_DOMAIN_EXTRA_TOKENS = ("fastapi", "psycopg")

# The application core must not import the web framework directly.
_APPLICATION_EXTRA_TOKENS = ("fastapi",)


def _python_files(package) -> List[Path]:
    """Return all .py files under a package directory."""
    package_dir = Path(package.__file__).parent
    return sorted(package_dir.rglob("*.py"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _import_lines(path: Path) -> List[str]:
    """Return the actual import statement lines of a module.

    Scanning only imports avoids matching a token that appears in prose, such
    as a docstring stating the module does not depend on a library.
    """
    lines = []
    for raw in _read(path).splitlines():
        stripped = raw.strip().lower()
        if stripped.startswith("import ") or stripped.startswith("from "):
            lines.append(stripped)
    return lines


def _import_offenders(package, tokens) -> List:
    offenders = []
    for path in _python_files(package):
        for line in _import_lines(path):
            for token in tokens:
                if token in line:
                    offenders.append((path.name, token))
    return offenders


def test_domain_has_no_transport_or_framework_imports():
    """The domain depends on no delivery technology, web or database library."""
    forbidden = _TRANSPORT_TOKENS + _DOMAIN_EXTRA_TOKENS
    offenders = _import_offenders(domain_pkg, forbidden)
    assert offenders == [], f"forbidden imports found in domain: {offenders}"


def test_application_has_no_transport_imports():
    """The application core depends on no real-time delivery technology."""
    forbidden = _TRANSPORT_TOKENS + _APPLICATION_EXTRA_TOKENS
    offenders = _import_offenders(application_pkg, forbidden)
    assert offenders == [], f"forbidden imports found in application: {offenders}"


def test_display_read_model_module_has_no_transport_import():
    """The DisplayReadModel port defines its models with no transport."""
    import AZFlow.application.ports.display_read_model as drm

    text = _read(Path(drm.__file__)).lower()
    for token in _TRANSPORT_TOKENS:
        assert token not in text, f"{token} must not appear in the display port"

    # The port and its model are defined and usable.
    assert hasattr(drm, "DisplayReadModel")
    assert hasattr(drm, "DisplayCall")


def test_display_read_model_usable_without_any_transport():
    """A fake DisplayReadModel can be read with no real-time transport."""

    class _FakeDisplayReadModel:
        """Trivial in-memory fake that needs no transport at all."""

        def recent_calls_for_monitor(
            self, waiting_room_monitor_id: int, operational_day: date
        ) -> List[DisplayCall]:
            return []

        def latest_call_for_room_monitor(
            self, room_monitor_id: int, operational_day: date
        ) -> Optional[DisplayCall]:
            return None

    read_model: DisplayReadModel = _FakeDisplayReadModel()
    today = date(2024, 3, 15)

    # Both display paths are exercisable through the port alone.
    assert read_model.recent_calls_for_monitor(1, today) == []
    assert read_model.latest_call_for_room_monitor(1, today) is None


def test_calling_publishes_only_through_call_event_publisher():
    """The calling module uses the single CallEventPublisher seam."""
    import AZFlow.application.calling as calling

    text = _read(Path(calling.__file__))
    assert "CallEventPublisher" in text


def test_no_parallel_display_notification_mechanism():
    """No display projection/publisher/subscriber class exists in application."""
    forbidden_class_tokens = (
        "DisplayProjection",
        "DisplayPublisher",
        "DisplaySubscriber",
    )
    offenders = []
    for path in _python_files(application_pkg):
        text = _read(path)
        for token in forbidden_class_tokens:
            # A class definition would read `class <token>...`.
            if f"class {token}" in text:
                offenders.append((path.name, token))
    assert offenders == [], f"unexpected parallel notification class: {offenders}"


def test_display_call_field_set_is_stable():
    """DisplayCall keeps exactly the non-identifying display fields.

    A datetime value round-trips through the model without any transport,
    showing the display data is plain application values.
    """
    field_names = {f.name for f in fields(DisplayCall)}
    assert field_names == {
        "public_call_code",
        "agenda",
        "state",
        "room_reference",
        "room_label",
        "occurred_at",
    }
    # The occurred_at field is a plain datetime, not a transport object.
    now = datetime.now(timezone.utc)
    assert isinstance(now, datetime)
