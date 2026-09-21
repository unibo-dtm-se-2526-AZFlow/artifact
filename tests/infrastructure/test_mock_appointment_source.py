from datetime import date, datetime

from AZFlow.application.ports.appointment_source import ExternalAppointmentData
from AZFlow.domain.patient_identifier import FISCAL_CODE, PatientIdentifier
from AZFlow.infrastructure.appointment_sources.mock import (
    MockAppointmentSource,
)


KNOWN_IDENTIFIER = PatientIdentifier(type=FISCAL_CODE, value="RSSMRA80A01H501U")
OPERATIONAL_DAY = date(2024, 3, 15)


def test_returns_appointments_for_known_identifier():
    source = MockAppointmentSource()

    appointments = source.find_for_day(KNOWN_IDENTIFIER, OPERATIONAL_DAY)

    assert appointments
    assert all(
        isinstance(appointment, ExternalAppointmentData) for appointment in appointments
    )


def test_returns_empty_for_unknown_identifier():
    source = MockAppointmentSource()
    unknown = PatientIdentifier(type=FISCAL_CODE, value="UNKNOWN00A00A000A")

    assert source.find_for_day(unknown, OPERATIONAL_DAY) == []


def test_is_deterministic_for_the_same_input():
    source = MockAppointmentSource()

    first = source.find_for_day(KNOWN_IDENTIFIER, OPERATIONAL_DAY)
    second = source.find_for_day(KNOWN_IDENTIFIER, OPERATIONAL_DAY)

    assert first == second


def test_returns_appointments_on_the_requested_operational_day():
    source = MockAppointmentSource()

    appointments = source.find_for_day(KNOWN_IDENTIFIER, OPERATIONAL_DAY)

    assert all(
        appointment.scheduled_at.date() == OPERATIONAL_DAY
        for appointment in appointments
    )


def test_external_appointment_reference_is_stable_across_days():
    source = MockAppointmentSource()

    day_one = source.find_for_day(KNOWN_IDENTIFIER, date(2024, 3, 15))
    day_two = source.find_for_day(KNOWN_IDENTIFIER, date(2024, 3, 16))

    assert [a.external_appointment_reference for a in day_one] == [
        a.external_appointment_reference for a in day_two
    ]


def test_accepts_a_custom_appointment_mapping():
    custom = {
        "CST0000000000000": [
            ExternalAppointmentData(
                external_source_code="MOCK",
                scheduled_at=datetime(2000, 1, 1, 8, 0),
                external_agenda_reference="AGENDA-X",
                external_appointment_reference="CUSTOM-1",
            )
        ]
    }
    source = MockAppointmentSource(appointments=custom)
    identifier = PatientIdentifier(type=FISCAL_CODE, value="CST0000000000000")

    appointments = source.find_for_day(identifier, OPERATIONAL_DAY)

    assert len(appointments) == 1
    assert appointments[0].external_appointment_reference == "CUSTOM-1"
    assert source.find_for_day(KNOWN_IDENTIFIER, OPERATIONAL_DAY) == []
