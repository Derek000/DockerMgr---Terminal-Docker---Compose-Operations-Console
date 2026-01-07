# Security Policy

## Threat model summary
- This tool can manage Docker workloads and can access Docker's API socket.
- Docker socket access can usually escalate to root, therefore treat tool access as privileged.

## Secure use recommendations
- Prefer `--read-only` unless you explicitly need to perform operations.
- Restrict host access (SSH hardening, MFA, least privilege).
- Avoid storing secrets in plain text environment variables.
  - Prefer file-based compose secrets as supported by the reconfigure wizard.

## Vulnerability reporting
If you discover a security issue, raise it privately with maintainers and include:
- reproduction steps
- affected version(s)
- suggested fix/mitigation
