"""Cost of Standard Webhooks signing/verification and of the delivery body serialisation.
    python scripts/sign_bench.py"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))      # run from anywhere

from worker.signing import sign, verify, webhook_headers

SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"


def bench(fn, n=20000):
    fn()
    samples = []
    for _ in range(5):
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        samples.append((time.perf_counter() - t0) / n * 1e6)
    return statistics.median(samples)


for size in (200, 2_000, 50_000, 250_000):
    payload = {"data": "x" * size, "n": 1}
    body = json.dumps({"id": "evt_x", "type": "t", "timestamp": "2026-01-01T00:00:00+00:00", "data": payload},
                      separators=(",", ":")).encode()
    n = 20000 if size <= 2_000 else 2000
    headers = webhook_headers(SECRET, "evt_x", body)
    print(f"body={len(body):>8} B  sign={bench(lambda: sign(SECRET, 'evt_x', 1700000000, body), n):8.1f} us  "
          f"verify={bench(lambda: verify(SECRET, headers, body), n):8.1f} us  "
          f"json.dumps={bench(lambda: json.dumps(payload, separators=(',', ':')).encode(), n):8.1f} us")
