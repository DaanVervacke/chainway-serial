# Security policy

## Supported versions

Only the latest release line receives security fixes.

## Reporting a vulnerability

Report vulnerabilities privately through [GitHub security advisories](https://github.com/DaanVervacke/chainway-serial/security/advisories/new).
Do not open a public issue for a vulnerability.

You will get a response within a week. Include reproduction steps and affected versions where you can.

## Scope

This library talks to an RFID reader over a serial or TCP link you own. Treat tag access passwords and kill passwords as secrets: they can permanently lock or destroy tags. Never commit passwords or captured frames from a live deployment. The `captures/` directory and the `.env` file are git-ignored for exactly this reason.
