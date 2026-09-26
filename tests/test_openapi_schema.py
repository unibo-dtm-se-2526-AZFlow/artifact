"""OpenAPI contract regression tests."""

from AZFlow.api import create_app


def test_shared_agenda_schema_is_exposed_once():
    schema = create_app().openapi()
    schemas = schema["components"]["schemas"]

    agenda_schemas = [
        name
        for name, definition in schemas.items()
        if definition.get("title") == "AgendaModel"
    ]

    assert agenda_schemas == ["AgendaModel"]
    assert schemas["AgendaModel"]["properties"].keys() == {"id", "name"}
