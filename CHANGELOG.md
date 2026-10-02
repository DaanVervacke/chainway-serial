# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Before 1.0, breaking changes ship as minor bumps.

## [Unreleased]

### Bug Fixes

- Match the wire handling to the decompiled SDK parsers
### Documentation

- Add the decoded Chainway UR4 wire protocol reference
- Correct the protocol reference from the SDK verification
- Add the official protocol document and the research findings
### Features

- Implement the frame codec, protocol, typed client and UDP discovery
- Accept both frame headers and add phase reporting inventory
- Implement every command of the official protocol document
### Maintenance

- Scaffold the repository with tooling, workflows and vendor archives
- Add the fake reader and the test suite
