# Contributing

Changes go through pull requests. Every pull request carries exactly one label from the release categories: breaking-change, new-feature, enhancement, bugfix, maintenance, documentation, dependencies.

## Setup

```bash
uv sync
uv run python -m scripts.check
```

`uv run python -m scripts.check` is the canonical gate. It stops at the first failure and runs exactly:

```text
ruff format --check .
ruff check .
mypy src tests scripts
coverage run -m pytest
coverage report
uv build
uv audit --locked --preview-features audit-command
```

After those, it checks that the `pyproject.toml` version equals the installed package version. After a version bump, run `uv sync` or the gate fails.

Coverage measures branches in `src/` and requires `fail_under = 98`. `uv audit` needs network access.

## Live hardware tests

`tests/hardware/` runs against a real reader. Without `CHAINWAY_URL` pytest skips the folder, so the gate never touches hardware.

```bash
CHAINWAY_URL=/dev/ttyUSB0 uv run pytest tests/hardware
```

`test_live.py` changes reader settings, restores them, reboots the reader with `software_reset` and ends with a factory restore. It writes the buzzer setting and the reader address back afterwards, and wipes every other stored setting. Over TCP it skips the factory restore, because the restore moves the reader to 192.168.99.202. `test_tags.py` needs at least one Gen2 tag with a 32-bit USER bank on the antenna, such as an Impinj Monza R6-P. It restores every tag write and never kills, permalocks or deactivates a tag. `test_tcp.py` runs only with a `socket://` URL. It opens competing connections, switches the reader to auto mode with UDP push and reboots it, restores the settings, and listens for discovery broadcasts on UDP port 1111.

`scripts/probe_chainway.py` sends every reader read command and a three second inventory, but no tag read, and writes the answers to `captures/probe.json`. Before the inventory it switches the inventory mode to EPC, TID and USER without the save flag, so the previous mode returns at the next power cycle. Without a URL it lists the readers UDP discovery finds.

```bash
uv run python -m scripts.probe_chainway /dev/ttyUSB0
```

`docs/protocol.md` records what the hardware confirmed, which commands the UR4 does not support, and the open items.

## Adding a command

Add all of the following:

- The byte layout in `docs/protocol.md` with a worked example frame, computed from the XOR rule over the length bytes, the command and the payload.
- A `Command` constant in `src/chainway_serial/const.py` and a typed `ChainwayClient` method with a docstring.
- A response branch in `tests/fake_reader.py`.
- Frame and parser tests pinning the wire bytes against the protocol reference.

## Changelog

`CHANGELOG.md` is generated with git-cliff from conventional commit subjects. Never edit it by hand. `feat:` and `fix:` subjects become the Features and Bug Fixes entries, `docs:` and `chore:` subjects land in the Documentation and Maintenance sections, and every other type is left out. Regenerate with `git-cliff --output CHANGELOG.md` and commit the result as `chore: regenerate the changelog`, a subject the changelog leaves out. At release, bump the version, run `uv sync`, render the release with `git-cliff --tag vX.Y.Z --output CHANGELOG.md`, commit as `chore: release vX.Y.Z`, tag `vX.Y.Z`, and push the tag. Publishing a GitHub release for the tag runs the release workflow, which uploads the package to PyPI. git-cliff writes the release heading and the compare links from the tags.

## Captures and confidential data

Raw probe output stays in `captures/`, which is git-ignored. Tag access passwords, kill passwords, and the addresses and captures of a live deployment are secrets. Redact them before sharing anything. The `.env` file is git-ignored for this reason. The MAC address of the development unit and its factory or lab addresses may appear in the repository.

## Protocol ground truth

The decompiled vendor SDKs were the first protocol source. Since October 2026 one UR4 checks them on hardware, see "Live verification" in `docs/protocol.md`. The decompiled trees are rebuilt from the three RAR archives at the repository root when needed. When live hardware contradicts `docs/protocol.md`, the document wins only after the capture proves it: record the frame in `captures/`, update the document, and pin the new bytes in a test.

## Test and repository rules

- Pytest uses `asyncio_mode = auto`. Warnings are errors.
- Ruff uses `select = ["ALL"]` with the documented ignore list in `pyproject.toml`. mypy runs in strict mode.
- Do not add code comments of any kind in any language. Only pragmas (`# noqa`, `# type: ignore`) and shebangs are allowed. Python docstrings document the public API.
- Never log passwords or reader credentials.
- Run a text-quality pass over all user-facing text before committing: README, CHANGELOG entries, docstrings, and error messages. No em dashes, no semicolon-joined clauses, no filler transitions.
- Do not mention AI, agents, or tooling in commit messages.
