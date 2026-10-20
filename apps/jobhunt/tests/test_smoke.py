import importlib


def test_package_imports() -> None:
    module = importlib.import_module("jobhunt")
    assert module.__doc__
