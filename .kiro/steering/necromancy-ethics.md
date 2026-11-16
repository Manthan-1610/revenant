---
inclusion: always
---

# Necromancy ethics: rules for resurrection

- Only resurrect **public** interfaces. Never reconstruct authentication or private user
  data, and never store personal data found in archived captures.
- Exhume caches captures of public API endpoints and docs pages only. It rejects any capture
  whose URL carries auth-like params (crumb, cookie, token, key, session, email).
- Respect the Internet Archive: rate-limit requests, cache aggressively, and identify the
  client with this User-Agent: `Revenant/0.1 (+https://github.com/Manthan-1610/revenant)`.
  Never put an email address in it.
- Revenants are served only under our own domain or through a local proxy on the user's
  own machine. Never impersonate the original company's domain on the public internet.
- Responses carry an `X-Revenant-Donor` header that names the living data source.
- No HTTPS interception except on the user's own devices, with explicit consent.
