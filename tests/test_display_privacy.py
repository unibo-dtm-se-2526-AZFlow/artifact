"""Display privacy guard at the read-model boundary.

Property 10 (Validates: Requirements 6.7, 6.8, 7.8, 7.9, 8.6, 8.7,
10.1-10.6, 12.6).

The DB test test_postgres_display_read_model.py checks the same privacy
property against real query output. This DB-free check asserts the DisplayCall
field set directly, giving a fast privacy guard independent of the database.
"""

from __future__ import annotations

from dataclasses import fields

from AZFlow.application.ports.display_read_model import DisplayCall

# The complete, non-identifying display field set.
_ALLOWED_FIELDS = {
    "public_call_code",
    "agenda",
    "state",
    "room_reference",
    "room_label",
    "occurred_at",
}

# Field names that would signal a leaked patient identifier.
_FORBIDDEN_FIELD_TOKENS = ("patient", "identifier", "name", "birth", "fiscal")


def test_display_call_has_exactly_the_non_identifying_field_set():
    """DisplayCall exposes exactly the allowed fields, nothing more."""
    field_names = {f.name for f in fields(DisplayCall)}
    assert field_names == _ALLOWED_FIELDS


def test_display_call_has_no_patient_identifier_field():
    """No DisplayCall field name hints at a patient identifier."""
    field_names = {f.name for f in fields(DisplayCall)}
    for name in field_names:
        lowered = name.lower()
        for token in _FORBIDDEN_FIELD_TOKENS:
            assert token not in lowered, f"field {name!r} may expose identity"
