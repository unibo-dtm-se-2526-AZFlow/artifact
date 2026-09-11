import AZFlow


def test_package_is_importable():
    assert AZFlow.__name__ == "AZFlow"


def test_main_runs_without_error():
    # main() must be callable so `python -m AZFlow` works.
    assert AZFlow.main() is None
