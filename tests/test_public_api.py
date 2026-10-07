"""Public API surface tests."""

import importlib
import importlib.metadata
import inspect

import pytest

import chainway_serial
from chainway_serial import __all__, client, const, discovery, exceptions, models, parsers


def test_all_entries_are_importable() -> None:
    for name in __all__:
        assert hasattr(chainway_serial, name)


def test_all_matches_the_public_namespace() -> None:
    public = {
        name
        for name in dir(chainway_serial)
        if not name.startswith("_") and not inspect.ismodule(getattr(chainway_serial, name))
    }
    assert public == set(__all__) - {"__version__"}
    assert hasattr(chainway_serial, "__version__")


def test_all_is_sorted() -> None:
    assert list(__all__) == sorted(__all__)


def test_reexports_are_identity_imports() -> None:
    for name in __all__:
        if name == "__version__":
            continue
        symbol = getattr(chainway_serial, name)
        sources = (client, const, discovery, exceptions, models, parsers)
        defining = [module for module in sources if symbol is getattr(module, name, None)]
        assert defining, f"{name} is not an identity re-export of a submodule symbol"


def test_version_falls_back_when_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raising(_name: object) -> str:
        msg = "chainway-serial is not installed"
        raise importlib.metadata.PackageNotFoundError(msg)

    monkeypatch.setattr(importlib.metadata, "version", raising)
    reloaded = importlib.reload(chainway_serial)
    assert reloaded.__version__ == "0.0.0"
    monkeypatch.undo()
    importlib.reload(chainway_serial)
    assert chainway_serial.__version__ != "0.0.0"
