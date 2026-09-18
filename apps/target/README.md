# Target API and worker

Python 3.12/FastAPI inside Compose. Public business operations are GET /probe, POST /login and POST /jobs; job list/detail, health/readiness and bounded metrics are available separately. The session operation is a synthetic Redis probe.

Only signed, bounded, run-scoped control authorizations may activate the three catalog faults. Private /_faults routes are excluded from browser proxies. Handler waits are cancellable; worker decisions use current fault state. Atomic enqueue/claim/ack scripts preserve intentional drops and recover interrupted leases with bounded retries and retention.

See [SPEC](../../docs/SPEC.md) for bounds and semantics and [QUALITY](../../docs/QUALITY.md) for tests. The Compose target health check uses /ready; a 200 /health response can describe intentional degradation. Redis job state is disposable demo data; immutable run history lives in control's independent SQLite volume.
