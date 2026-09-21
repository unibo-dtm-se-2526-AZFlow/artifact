from AZFlow.application.ports.check_in_repository import (
    PUBLIC_CALL_CODE_MIN_DIGITS,
    ResolvedAgenda,
    ResolvedQueue,
    format_public_call_code,
)
from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.external_source import ExternalSource
from AZFlow.domain.ticket_master import TicketMaster


def test_format_public_call_code_zero_pads_to_minimum_digits():
    assert format_public_call_code("AAA", 1) == "AAA001"
    assert format_public_call_code("AAA", 42) == "AAA042"
    assert PUBLIC_CALL_CODE_MIN_DIGITS == 3


def test_format_public_call_code_keeps_larger_sequences():
    assert format_public_call_code("AAA", 1000) == "AAA1000"


def _external_agenda() -> ExternalAgenda:
    agenda = Agenda(id=1, name="Cardiology")
    source = ExternalSource(id=1, code="MOCK", name="Mock", connector_type="mock")
    return ExternalAgenda(agenda=agenda, source=source, external_reference="AGENDA-A")


def test_resolved_agenda_reports_active_queue_presence():
    external_agenda = _external_agenda()
    with_queue = ResolvedAgenda(
        external_agenda=external_agenda,
        agenda=external_agenda.agenda,
        active_queues=[
            ResolvedQueue(queue_id=1, ticket_master=TicketMaster(id=1, prefix="AAA"))
        ],
    )
    without_queue = ResolvedAgenda(
        external_agenda=external_agenda,
        agenda=external_agenda.agenda,
    )

    assert with_queue.has_active_queue() is True
    assert without_queue.has_active_queue() is False
