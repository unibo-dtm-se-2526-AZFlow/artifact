"""Privacy and transport-independence guards for the WebSocket transport.

Property 3 (Validates: Requirements 6.1, 6.2): every WebSocket message carries
exactly the non-identifying DisplayCall fields and no Patient Identifier.
Property 7 (Validates: Requirement 8.1): the domain and application core import
no WebSocket symbol, so the adapter can be added or removed by changing only
composition and the API layer.

These are DB-free and run in the normal test run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List

import AZFlow.application as application_pkg
import AZFlow.domain as domain_pkg
from AZFlow.application.ports.display_read_model import DisplayCall
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.infrastructure.events.websocket_call_hub import display_call_json

_ALLOWED_FIELDS = {
    "public_call_code",
    "agenda",
    "state",
    "room_reference",
    "room_label",
    "occurred_at",
}
_WEBSOCKET_TOKENS = ("websocket", "starlette.websockets")
PATIENT_IDENTIFIER = "RSSMRA80A01H501U"


def _display_call() -> DisplayCall:
    return DisplayCall(
        public_call_code="AAA001",
        agenda=Agenda(id=3, name="Cardiology"),
        state=ServiceAccessState.CALLED,
        room_reference="ROOM-1",
        room_label="Room 1",
        occurred_at=datetime(2024, 3, 15, 9, 31, tzinfo=timezone.utc),
    )


def test_message_json_has_exactly_the_non_identifying_fields():
    """A serialised call message exposes exactly the allowed fields."""
    payload = display_call_json(_display_call())

    assert set(payload.keys()) == _ALLOWED_FIELDS
    assert set(payload["agenda"].keys()) == {"id", "name"}


def test_message_json_never_exposes_patient_identity():
    """No serialised field name or value hints at a patient identifier."""
    payload = display_call_json(_display_call())

    text = str(payload).lower()
    for token in ("patient", "identifier", "birth", "fiscal"):
        assert token not in text
    assert PATIENT_IDENTIFIER not in str(payload)


def _import_lines(path: Path) -> List[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip().lower()
        if stripped.startswith("import ") or stripped.startswith("from "):
            lines.append(stripped)
    return lines


def _offenders(package) -> List:
    package_dir = Path(package.__file__).parent
    offenders = []
    for path in sorted(package_dir.rglob("*.py")):
        for line in _import_lines(path):
            for token in _WEBSOCKET_TOKENS:
                if token in line:
                    offenders.append((path.name, token))
    return offenders


def test_domain_imports_no_websocket_symbol():
    """The domain package imports no WebSocket symbol."""
    assert _offenders(domain_pkg) == []


def test_application_imports_no_websocket_symbol():
    """The application package imports no WebSocket symbol."""
    assert _offenders(application_pkg) == []
