from AZFlow.application.errors import (
    ApplicationError,
    MissingRoomReferenceError,
    NoPatientToCallError,
    ServiceAccessNotCallableError,
    ServiceAccessNotVisibleError,
)


def test_missing_room_reference_error_is_application_error():
    assert isinstance(MissingRoomReferenceError(), ApplicationError)


def test_no_patient_to_call_error_carries_queue_id():
    error = NoPatientToCallError(7)

    assert isinstance(error, ApplicationError)
    assert error.queue_id == 7


def test_service_access_not_visible_error_carries_service_access_id():
    error = ServiceAccessNotVisibleError(12)

    assert isinstance(error, ApplicationError)
    assert error.service_access_id == 12


def test_service_access_not_callable_error_carries_service_access_id():
    error = ServiceAccessNotCallableError(12)

    assert isinstance(error, ApplicationError)
    assert error.service_access_id == 12
