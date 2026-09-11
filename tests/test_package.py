import uvicorn

import AZFlow


def test_package_is_importable():
    assert AZFlow.__name__ == "AZFlow"


def test_main_runs_the_asgi_server(monkeypatch):
    captured = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured["kwargs"] = kwargs

    monkeypatch.setattr(uvicorn, "run", fake_run)

    assert AZFlow.main() is None
    assert captured["app"] == "AZFlow.api:app"
    assert "host" in captured["kwargs"]
    assert "port" in captured["kwargs"]
