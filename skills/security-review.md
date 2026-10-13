---
name: security-review
description: Checklist for finding vulnerabilities and handling secrets
triggers: security, secure, vulnerability, vulnerabilities, auth, authentication, password, secret, token, injection, xss, csrf, sicherheit, sicher
---
# Security review

Look for these, with concrete evidence in code:
- **Injection**: user input in shell commands (`shell=True`, backticks), SQL string concatenation, `eval`, template injection, path traversal (`../`), SSRF (user-controlled URLs), unsafe deserialization (`pickle`, `yaml.load`).
- **Web**: unescaped output (XSS, `innerHTML`), missing CSRF protection on state-changing requests, open CORS, cookies without `HttpOnly`/`Secure`/`SameSite`, open redirects, secrets in client code.
- **Auth**: missing authorization checks on each endpoint, IDs trusted from the client, weak password storage (use argon2/bcrypt), tokens in URLs, no rate limit on login.
- **Secrets**: keys/passwords in the repo, in logs, in error messages, in `.env` that is committed. Load from the environment; add the file to `.gitignore`.
- **Dependencies and config**: debug mode on, default credentials, world-writable files, services bound to 0.0.0.0 that need not be.
For each finding: file:line, how it can be exploited, the fix. Do not report theoretical issues without a path from untrusted input to the sink.
