"""Integration tests for the Queue policy reference catalog."""

from AZFlow.domain.queue import QueuePolicy


def test_queue_policy_catalog_matches_domain(connection):
    """Keep persisted reference policies aligned with supported behaviour."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT code FROM queue_policy")
        database_policies = {row[0] for row in cursor.fetchall()}

    assert database_policies == {policy.value for policy in QueuePolicy}
