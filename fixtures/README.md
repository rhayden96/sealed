# Fixtures

Offline seal replay. `GET /fixtures` on control. Does not unseal. Does not inject.

| file | verdict |
|------|---------|
| `seals/handler_latency_pass.json` | `pass` |
| `seals/redis_down_aborted.json` | `aborted` |

There is no `worker_drop` seal. The agent proposes that draft and does not run it.
