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
uv audit
```

Coverage measures branches in `src/` and requires `fail_under = 98`. `uv audit` needs network access.

## Adding a command

Add all of the following:

- The byte layout in `docs/protocol.md` with a worked example frame, computed from the XOR rule over the length bytes, the command and the payload.
- A `Command` constant in `src/chainway_serial/const.py` and a typed `ChainwayClient` method with a docstring.
- A response branch in `tests/fake_reader.py`.
- Frame and parser tests pinning the wire bytes against the protocol reference.

## Changelog

`CHANGELOG.md` is generated with git-cliff from conventional commit subjects. Never edit it by hand. `feat:` and `fix:` subjects become the Features and Bug Fixes entries, `docs:` and `chore:` subjects land in the Documentation and Maintenance sections, and every other type is left out. Regenerate with `git-cliff --output CHANGELOG.md` after committing.

## Captures and confidential data

Raw probe output stays in `captures/`, which is git-ignored. Tag access passwords, kill passwords, and reader network details are secrets: redact them before sharing anything. The `.env` file is git-ignored for exactly this reason.

## Protocol ground truth

The vendor SDKs are the only protocol source until a reader is on hand. The decompiled trees are rebuilt from the three RAR archives at the repository root when needed. When live hardware contradicts `docs/protocol.md`, the document wins only after the capture proves it: record the frame in `captures/`, update the document, and pin the new bytes in a test.

## Test and repository rules

- Pytest uses `asyncio_mode = auto`. Warnings are errors.
- Ruff uses `select = ["ALL"]` with the documented ignore list in `pyproject.toml`. mypy runs in strict mode.
- Do not add narrative code comments. Docstrings document the public API.
- Never log passwords or reader credentials.
- Run a text-quality pass over all user-facing text before committing: README, CHANGELOG entries, docstrings, and error messages. No em dashes, no semicolon-joined clauses, no filler transitions.
- Do not mention AI, agents, or tooling in commit messages.
