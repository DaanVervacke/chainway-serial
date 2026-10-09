# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Before 1.0, breaking changes ship as minor bumps.

## [Unreleased]

### Bug Fixes

- Fire the connection-lost callback once and outside the close wait
- Wait out the reader's mute window after a configuration write
- Report OS-level link failures as ChainwayConnectionError
- Refuse internal baud codes outside UartBaudRate
- Raise a response error for an unsupported pending baud code
- Keep the probe script running when a read fails
- Wait out the module mute after a factory restore
- Stop a leftover scan when connecting
- Reopen a TCP link that resets before its first answer
- Listen 12 seconds for reader discovery by default
- Validate the subnet mask and gateway of a reader address
- Sort discovered readers by numeric address and wrap port errors
- Keep the keepalive from reopening a link

### Documentation

- Correct the readme scope table and protocol gaps
- Align the guides with the current client api
- Record firmware 7.40.1 live verification in the protocol trail
- Correct the device ID, reset and GPI docstrings from live findings
- Map the UR4 mainboard and module split and the boot console
- Document internal baud code 0x01 as 57600 and the SWD recovery
- Record setting persistence and drop local file references
- Update the readme with the live verification status
- Replace stale unverified notes with live findings
- Record the live tag session findings
- Record that a closed link leaves the scan running
- Record that a factory restore also resets the mainboard settings
- Trim the readme to install, usage and development
- Rewrite the documentation pages for library users
- Record the TCP link behavior and the factory address reset
- Record UDP push, scan handover and TCP timing
- Align the guides with TCP testing, reset timing and the gate
- Record that the reader keeps an idle TCP link open
- Note that the UR4 rejects a stored antenna work time
- Drop the module settings example the UR4 does not answer
- Show the protocol type as read only on the UR4
- List every command the UR4 does not support on one page
- Document the tag and connection lost callback types
- Narrow the secrets rule to passwords and live deployment data
- Ban every code comment in the contributing rules

### Features

- Export SensorSubcommand
- Add UART baud rate get and set commands
- Replace get_gpo with get_gpi
- Add the reserved memory bank for password access
- Raise ChainwayUnsupportedCommandError and name tag error codes

### Maintenance

- Update the changelog
- Update the changelog
- Update the changelog
- Add UR4 mainboard firmware dumps
- Update the changelog
- Update the changelog
- Update the changelog
- Update the changelog
- Update the changelog
- Update the changelog
- Update the changelog
- Bump release-drafter to 7.9.0

## [0.2.0] - 2026-10-04

### Bug Fixes

- Clear the scan state on a failed stop and contain callback errors

### Documentation

- Correct the changelog grouping and the probe scope claim
- Add the native library command catalog to the protocol reference
- Add the 2025 SDK findings to the protocol reference

### Features

- Add the native library commands and the remaining reader commands
- Add frequency reporting and the protected mode command

### Maintenance

- Enforce docstrings on the public api
- Align the changelog tooling with the library family

## [0.1.0] - 2026-10-02

### Bug Fixes

- Match the wire handling to the decompiled SDK parsers
- Probe script crash and dead tag collection
- Move the start inventory guard inside the request lock

### Documentation

- Add the decoded Chainway UR4 wire protocol reference
- Correct the protocol reference from the SDK verification
- Add the official protocol document and the research findings
- Fix the gpo example and the install instructions

### Features

- Implement the frame codec, protocol, typed client and UDP discovery
- Accept both frame headers and add phase reporting inventory
- Implement every command of the official protocol document
- Export the LinkFrequency enum

### Maintenance

- Scaffold the repository with tooling, workflows and vendor archives
- Add the fake reader and the test suite
- Remove vendor demo archives and protocol pdf from the repository

[Unreleased]: https://github.com/DaanVervacke/chainway-serial/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/DaanVervacke/chainway-serial/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/DaanVervacke/chainway-serial/releases/tag/v0.1.0

