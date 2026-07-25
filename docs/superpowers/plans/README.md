# Roadmap Summary

## Shipped Phases

- Phase 1: Flask scaffold, local auth, group-based tab permissions, admin shell.
- Phase 2: Dashboard health polling, FAZ target management, Docker TLS deployment.
- Phase 3: Log Search UI, filter parsing, field picker, results export.

## Ongoing Priorities

- Improve documentation and contributor workflows for public collaboration.
- Continue validating FAZ API behavior across firmware and permission variations.
- Expand automated test coverage when new routes or background behaviors are added.

## Contributor Expectations

- Keep runtime secrets and deployment-local state out of version control.
- Treat FAZ request/response behavior as firmware-sensitive; validate against tests and,
  when needed, against a real appliance.