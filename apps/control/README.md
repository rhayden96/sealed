# Control API

Python 3.12/FastAPI at loopback :8081 in Compose. Routes delegate policy evaluation, lifecycle coordination, bounded evidence collection, target delivery, game-day operations and SQLite storage to focused modules.

One control process/replica is supported. Admission reserves the run before target I/O; cleanup/recovery retain ownership. Immutable seals and run events persist independently of Redis. On restart the lifecycle cleans interrupted runs and records failure without re-injection. Planner diagnostics are separately bounded and sanitized.

See [SPEC](../../docs/SPEC.md) for endpoints, verdicts, policy and recovery contracts; [QUALITY](../../docs/QUALITY.md) for unit, type and Compose acceptance commands; and [WALKTHROUGH](../../docs/WALKTHROUGH.md) for operator flows.
