# Offline seal fixtures

Files in seals/ are exact historical/synthetic replay examples. They predate measured evidence; their recorded verdicts are not evidence that a current experiment passed. The console explicitly identifies missing reason/evidence instead of fabricating observations.

The console build copies them into its own /replay/seals/ assets. After building once, run only web with `docker compose up -d --no-deps --pull never web`, then open http://localhost:5173/?view=fixtures. Target, worker, Redis, control and an inference provider are unnecessary. Initial dependency/image downloads are separate from offline replay. The compatible control /fixtures API remains available when control is running. Replay performs no mutations.
