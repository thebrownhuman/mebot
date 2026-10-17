# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.9.x (latest release) | yes |
| older | no, please upgrade ([docs/upgrading.md](docs/upgrading.md)) |

Installs with telemetry on get a red, non-dismissible banner in the admin panel while their
version has a published advisory.

## Reporting a vulnerability

Please **don't open a public issue**. Report privately through GitHub:
**Security → Report a vulnerability** on this repository (a private security advisory).
If that isn't available to you, email `<security-contact-email>` (set by the maintainer
before the repository goes public).

Include what you found, how to reproduce it, the version (`/api/health` reports it) and the
impact you expect. You'll get an acknowledgement within 7 days. Once a fix is released, the
advisory is published and the registry starts flagging affected versions. Credit is given
unless you'd rather not be named.

In scope: the mebot app (backend, frontend, embed, widget loader), the Docker image, and the
registry service in `registry/`. See [docs/security.md](docs/security.md) for the threat
model; things it lists as out of scope (for example someone with shell access to the server)
aren't vulnerabilities in mebot.
