"""Packaging tests: metadata, typing marker, and build backend alignment."""

import tomllib
from pathlib import Path

import chainway_serial

REPO = Path(__file__).resolve().parent.parent


def test_version_is_defined() -> None:
    assert chainway_serial.__version__ != "0.0.0"
    assert chainway_serial.__version__


def test_pyproject_name_python_and_license() -> None:
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert data["project"]["name"] == "chainway-serial"
    assert data["project"]["requires-python"] == ">=3.14"
    assert data["project"]["license"] == "MIT"


def test_uv_required_version_matches_the_build_backend() -> None:
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    build_requirement = data["build-system"]["requires"]
    assert len(build_requirement) == 1
    assert build_requirement[0] == f"uv_build{data['tool']['uv']['required-version']}"


def test_py_typed_ships_with_the_package() -> None:
    marker = Path(chainway_serial.__file__).parent / "py.typed"
    assert marker.is_file()


def test_runtime_dependencies_stay_minimal() -> None:
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert data["project"]["dependencies"] == ["serialx>=1.10"]
