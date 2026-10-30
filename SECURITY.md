# Security

## Reporting a vulnerability

Please don't open a public issue for security problems. Report them privately:

- through GitHub: **Security → Report a vulnerability** on this repository, or
- by email to info@openworks.co.za with "LineGuard security" in the subject.

Say what you found, how to reproduce it, and which version or commit you tested. We aim to reply within five working days and to fix confirmed issues in the next release, crediting you if you'd like.

## Supported versions

Security fixes go into the latest release only. Run a tagged release (`git checkout vX.Y.Z`), not whatever is newest on `main`.

## Scope and design notes

The audits so far, with the threat model and the known limitations, are in [docs/](docs/). In short:

- **The laptop.** It trusts its own browser only through `localhost` or an IP address, and only with a header other websites can't send.
- **Phones.** They use per-device tokens, which can be revoked from the dashboard.
- **The vehicle Wi-Fi.** The laptop link inside the vehicle is plain HTTP over the laptop's own WPA2 Wi-Fi, so treat that Wi-Fi password like a key.
- **Hosted servers.** They need HTTPS, a strong password, and a proxy that checks the login before accepting large uploads (see `deploy/vps/`).
