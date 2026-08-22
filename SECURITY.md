# Security policy

## Supported versions

This portfolio repository is maintained on the `main` branch only. Historical commits and unmerged branches are not supported.

## Reporting a vulnerability

Do not open a public issue for suspected vulnerabilities, exposed credentials, or sensitive data.

Report privately through [GitHub private vulnerability reporting](https://github.com/umutseve4/econ-lakehouse/security/advisories/new). Include:

- the affected file, endpoint, or workflow;
- reproducible steps;
- expected and observed behavior;
- impact assessment;
- a suggested mitigation, if known.

Never include a real `EVDS_API_KEY`, cloud credential, or other secret in a report, test fixture, commit, log, or screenshot. Rotate any credential immediately if exposure is suspected.

## Security boundaries

- Live EVDS access requires the `EVDS_API_KEY` GitHub Actions secret or environment variable.
- MinIO credentials in CI are disposable test-only values for an isolated container; they must never be reused outside CI.
- The FastAPI and Streamlit services are portfolio demonstrations, not hardened multi-tenant production services.
- Dependency updates must pass the repository's complete CI workflows before merge.
