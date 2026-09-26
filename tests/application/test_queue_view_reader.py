import dataclasses
from datetime import date, datetime
from typing import List, Optional

import pytest

from AZFlow.application.ports.queue_view_reader import (
    CandidateServiceAccess,
    QueueViewReader,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import Queue, QueuePolicy, QueueStatus
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster


def _agenda() -> Agenda:
    return Agenda(id=3, name="Cardiology")


def test_candidate_service_access_carries_its_fields():
    agenda = _agenda()
    candidate = CandidateServiceAccess(
        service_access_id=12,
        daily_presence_id=7,
        agenda=agenda,
        state=ServiceAccessState.WAITING,
        public_call_code="AAA001",
        checked_in_at=datetime(2024, 1, 1, 8, 0),
        scheduled_at=datetime(2024, 1, 1, 9, 0),
    )

    assert candidate.service_access_id == 12
    assert candidate.daily_presence_id == 7
    assert candidate.agenda == agenda
    assert candidate.state is ServiceAccessState.WAITING
    assert candidate.public_call_code == "AAA001"
    assert candidate.scheduled_at == datetime(2024, 1, 1, 9, 0)


def test_scheduled_at_is_optional_and_defaults_to_none():
    candidate = CandidateServiceAccess(
        service_access_id=13,
        daily_presence_id=8,
        agenda=_agenda(),
        state=ServiceAccessState.WAITING,
        public_call_code="AAA002",
        checked_in_at=datetime(2024, 1, 1, 8, 0),
    )

    assert candidate.scheduled_at is None


def test_candidate_service_access_is_immutable():
    candidate = CandidateServiceAccess(
        service_access_id=12,
        daily_presence_id=7,
        agenda=_agenda(),
        state=ServiceAccessState.WAITING,
        public_call_code="AAA001",
        checked_in_at=datetime(2024, 1, 1, 8, 0),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.public_call_code = "AAA999"  # type: ignore[misc]


def test_any_object_matching_the_protocol_is_a_queue_view_reader():
    agenda = _agenda()
    queue = Queue(
        id=1,
        status=QueueStatus.ACTIVE,
        policy=QueuePolicy.BY_ARRIVAL,
        ticket_master=TicketMaster(id=1, prefix="AAA"),
        agendas=[agenda],
    )
    candidate = CandidateServiceAccess(
        service_access_id=12,
        daily_presence_id=7,
        agenda=agenda,
        state=ServiceAccessState.WAITING,
        public_call_code="AAA001",
        checked_in_at=datetime(2024, 1, 1, 8, 0),
    )

    class InMemoryReader:
        def load_queue(self, queue_id: int) -> Optional[Queue]:
            return queue if queue_id == queue.id else None

        def list_service_accesses(
            self,
            agenda_ids: List[int],
            operational_day: date,
        ) -> List[CandidateServiceAccess]:
            return [candidate] if agenda.id in agenda_ids else []

    reader: QueueViewReader = InMemoryReader()

    assert reader.load_queue(1) is queue
    assert reader.load_queue(2) is None
    assert reader.list_service_accesses([agenda.id], date(2024, 1, 1)) == [candidate]
    assert reader.list_service_accesses([999], date(2024, 1, 1)) == []
