- [ ] `uv run python -m scripts.check` passes completely.
- [ ] The PR carries one of the seven labels: `breaking-change`, `new-feature`, `enhancement`, `bugfix`, `maintenance`, `documentation`, `dependencies`.
- [ ] Commit subjects follow conventional commits, so git-cliff picks the change up for `CHANGELOG.md`.

For command or model changes, all of the following are present:

- [ ] The byte layout is documented in `docs/protocol.md` with a worked example frame.
- [ ] A `Command` constant in `src/chainway_serial/const.py` and a typed `ChainwayClient` method with a docstring.
- [ ] The fake reader in `tests/fake_reader.py` answers the new command.
- [ ] Frame and parser tests pin the wire bytes against `docs/protocol.md`.
