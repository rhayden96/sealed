"""Worker container readiness, independent of the target API's observation cut."""

import json
import math
import os
import time

from redis import Redis

from sealed_target.worker import HEARTBEAT_FRESH_S, HEARTBEAT_KEY


def main() -> int:
    try:
        with Redis.from_url(os.environ["REDIS_URL"], socket_timeout=2, socket_connect_timeout=2) as client:
            raw = client.get(HEARTBEAT_KEY)
        data = json.loads(raw) if raw else {}
        at = data.get("at") if isinstance(data, dict) else None
        return 0 if isinstance(at, (int, float)) and not isinstance(at, bool) and math.isfinite(at) and -1 <= time.time() - at <= HEARTBEAT_FRESH_S else 1
    except (OSError, ValueError, TypeError, KeyError):
        return 1
    except Exception:
        # Health checks emit no credentials or Redis connection details.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
