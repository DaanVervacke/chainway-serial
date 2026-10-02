# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Before 1.0, breaking changes ship as minor bumps.

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
