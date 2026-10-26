from datetime import datetime

from cmon.collect.limiter import Limiter

lim = Limiter(2.0, 1.0, 30)
t = datetime(2026, 10, 26, 8, 0, 0)
for i in range(8):
    at = lim.reserve(t, "mock-taobao", f"I{i}")
    print(f"I{i}: asked={t.time()} at={at.time()} gap={(at - t).total_seconds():.1f}s")
    if at > t:
        t = at