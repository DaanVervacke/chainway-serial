"""Local CI gate: run every check tool in order and stop at the first failure."""

import subprocess
import sys
import tomllib
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

COMMANDS: tuple[tuple[str, ...], ...] = (
    ("uv", "run", "ruff", "format", "--check", "."),
    ("uv", "run", "ruff", "check", "."),
    ("uv", "run", "mypy", "src", "tests", "scripts", "hardware"),
    ("uv", "run", "coverage", "run", "-m", "pytest"),
    ("uv", "run", "coverage", "report"),
    ("uv", "build"),
    ("uv", "audit", "--locked", "--preview-features", "audit-command"),
)


def run_command(command: Sequence[str]) -> int:
    """Run one command and return its exit code without raising on failure."""
    print(f"\n$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, check=False)
    return completed.returncode


def check_version_alignment() -> int:
    """Compare the pyproject version with the installed package version."""
    with Path("pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    declared = data["project"]["version"]
    installed = version("chainway-serial")
    if declared != installed:
        print(
            f"pyproject.toml declares {declared} but the installed package reports {installed}",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    """Run all check commands in sequence and propagate the first failure's code."""
    for command in COMMANDS:
        return_code = run_command(command)
        if return_code != 0:
            if "ruff" in command:
                print(
                    "\nhint: format/lint failures are usually auto-fixable: "
                    "uv run ruff format . && uv run ruff check . --fix",
                    file=sys.stderr,
                )
            return return_code
    return check_version_alignment()


if __name__ == "__main__":
    sys.exit(main())
