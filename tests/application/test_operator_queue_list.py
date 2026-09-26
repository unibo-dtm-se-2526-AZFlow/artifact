from datetime import date, datetime

from AZFlow.application.operator_queue_list import OperatorQueueListService
from AZFlow.application.ports.queue_view_reader import CandidateServiceAccess
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import Queue, QueuePolicy, QueueStatus
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster
from tests.application.fakes import FakeQueueViewReader

_DAY = date(2024, 5, 20)
_AGENDA = Agenda(id=1, name="Cardiology")


def _candidate(
    service_access_id: int,
    state: ServiceAccessState,
    scheduled_at: datetime,
) -> CandidateServiceAccess:
    return CandidateServiceAccess(
        service_access_id=service_access_id,
        daily_presence_id=service_access_id,
        agenda=_AGENDA,
        state=state,
        public_call_code=f"AAA{service_access_id:03d}",
        checked_in_at=datetime(2024, 5, 20, 8, 0),
        scheduled_at=scheduled_at,
    )


def _service(candidates):
    queue = Queue(
        id=1,
        status=QueueStatus.ACTIVE,
        policy=QueuePolicy.BY_APPOINTMENT,
        ticket_master=TicketMaster(id=1, prefix="AAA"),
        agendas=[_AGENDA],
    )
    return OperatorQueueListService(
        FakeQueueViewReader({queue.id: queue}, candidates)
    )


def test_list_contains_waiting_and_suspended_with_state():
    service = _service(
        [
            _candidate(1, ServiceAccessState.WAITING, datetime(2024, 5, 20, 9)),
            _candidate(2, ServiceAccessState.SUSPENDED, datetime(2024, 5, 20, 10)),
        ]
    )

    view = service.view(1, _DAY)

    assert [entry.service_access_id for entry in view.entries] == [1, 2]
    assert [entry.state for entry in view.entries] == [
        ServiceAccessState.WAITING,
        ServiceAccessState.SUSPENDED,
    ]
    assert view.entries[0].checked_in_at == datetime(2024, 5, 20, 8, 0)


def test_list_excludes_called_and_admitted():
    service = _service(
        [
            _candidate(1, ServiceAccessState.WAITING, datetime(2024, 5, 20, 9)),
            _candidate(2, ServiceAccessState.CALLED, datetime(2024, 5, 20, 10)),
            _candidate(3, ServiceAccessState.ADMITTED, datetime(2024, 5, 20, 11)),
        ]
    )

    view = service.view(1, _DAY)

    assert [entry.service_access_id for entry in view.entries] == [1]


def test_suspended_entry_keeps_normal_queue_position():
    service = _service(
        [
            _candidate(1, ServiceAccessState.WAITING, datetime(2024, 5, 20, 10)),
            _candidate(2, ServiceAccessState.SUSPENDED, datetime(2024, 5, 20, 9)),
        ]
    )

    view = service.view(1, _DAY)

    assert [entry.service_access_id for entry in view.entries] == [2, 1]
