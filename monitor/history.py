"""Long-term usage history in SQLite (%APPDATA%\\SystemResourceMonitor\\history.db).

Samples arrive about once a second; they are averaged into 10-second rows (with the
peak kept) so 30 days of history stays around 260k rows per device.
"""
import os
import sqlite3
import threading
import time

BUCKET_SECONDS = 10
LOCAL_DEVICE = "__local__"
METRICS = ("cpu", "memory", "gpu", "gpu_memory")


def default_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "SystemResourceMonitor", "history.db")


class HistoryStore:
    def __init__(self, path=None):
        self.path = path or default_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS samples (
                ts REAL NOT NULL, device TEXT NOT NULL,
                cpu REAL, cpu_max REAL, memory REAL, memory_max REAL,
                gpu REAL, gpu_max REAL, gpu_memory REAL)""")
        self._db.execute("CREATE INDEX IF NOT EXISTS samples_device_ts ON samples(device, ts)")
        self._db.commit()
        self._buckets = {}  # device -> {"start": ts, "values": {metric: [..]}}
        self._last_prune = 0.0

    # ---------------- writing ----------------

    def add(self, device, cpu, memory, gpu, gpu_memory, now=None):
        now = now or time.time()
        values = {"cpu": cpu, "memory": memory, "gpu": gpu, "gpu_memory": gpu_memory}
        with self._lock:
            bucket = self._buckets.get(device)
            if bucket is None:
                bucket = self._buckets[device] = {"start": now, "values": {m: [] for m in METRICS}}
            for metric, value in values.items():
                if value is not None:
                    bucket["values"][metric].append(float(value))
            if now - bucket["start"] >= BUCKET_SECONDS:
                self._write_bucket(device, bucket)
                del self._buckets[device]

    def _write_bucket(self, device, bucket):
        def avg(metric):
            items = bucket["values"][metric]
            return sum(items) / len(items) if items else None

        def peak(metric):
            items = bucket["values"][metric]
            return max(items) if items else None

        if not bucket["values"]["cpu"] and not bucket["values"]["memory"]:
            return
        self._db.execute(
            "INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?)",
            (bucket["start"] + BUCKET_SECONDS / 2, device, avg("cpu"), peak("cpu"),
             avg("memory"), peak("memory"), avg("gpu"), peak("gpu"), avg("gpu_memory")))
        self._db.commit()

    def flush(self):
        with self._lock:
            for device, bucket in list(self._buckets.items()):
                self._write_bucket(device, bucket)
            self._buckets.clear()

    def prune(self, keep_days):
        """Delete rows older than keep_days (runs at most once an hour)."""
        now = time.time()
        if now - self._last_prune < 3600:
            return
        self._last_prune = now
        with self._lock:
            self._db.execute("DELETE FROM samples WHERE ts < ?", (now - keep_days * 86400,))
            self._db.commit()

    def close(self):
        self.flush()
        with self._lock:
            self._db.close()

    # ---------------- reading ----------------

    def devices(self):
        with self._lock:
            rows = self._db.execute(
                "SELECT device, MAX(ts) FROM samples GROUP BY device ORDER BY MAX(ts) DESC").fetchall()
        return [row[0] for row in rows]

    def series(self, device, since, max_points=600):
        """Rows (ts, cpu, memory, gpu, gpu_memory), averaged so at most max_points are returned."""
        span = max(1.0, time.time() - since)
        step = max(BUCKET_SECONDS, span / max_points)
        with self._lock:
            return self._db.execute(
                """SELECT AVG(ts), AVG(cpu), AVG(memory), AVG(gpu), AVG(gpu_memory)
                   FROM samples WHERE device = ? AND ts >= ?
                   GROUP BY CAST(ts / ? AS INTEGER) ORDER BY 1""",
                (device, since, step)).fetchall()

    def stats(self, device, since):
        """Average and peak of each metric in the period, plus sample count."""
        with self._lock:
            row = self._db.execute(
                """SELECT COUNT(*), AVG(cpu), MAX(cpu_max), AVG(memory), MAX(memory_max),
                          AVG(gpu), MAX(gpu_max), AVG(gpu_memory), MIN(ts), MAX(ts)
                   FROM samples WHERE device = ? AND ts >= ?""", (device, since)).fetchone()
        count = row[0] or 0
        if not count:
            return None
        return {
            "rows": count,
            "cpu": {"avg": row[1], "max": row[2]},
            "memory": {"avg": row[3], "max": row[4]},
            "gpu": {"avg": row[5], "max": row[6]},
            "gpu_memory": {"avg": row[7]},
            "first": row[8], "last": row[9],
        }

    def periods(self, device, since, period_seconds):
        """Per-hour (or per-day) averages and peaks, for the AI period analysis."""
        with self._lock:
            rows = self._db.execute(
                """SELECT MIN(ts), AVG(cpu), MAX(cpu_max), AVG(memory), MAX(memory_max),
                          AVG(gpu), MAX(gpu_max)
                   FROM samples WHERE device = ? AND ts >= ?
                   GROUP BY CAST(ts / ? AS INTEGER) ORDER BY 1""",
                (device, since, period_seconds)).fetchall()
        result = []
        for start, cpu, cpu_max, mem, mem_max, gpu, gpu_max in rows:
            result.append({
                "start": time.strftime("%Y-%m-%d %H:%M", time.localtime(start)),
                "cpu_avg": _r(cpu), "cpu_peak": _r(cpu_max),
                "memory_avg": _r(mem), "memory_peak": _r(mem_max),
                "gpu_avg": _r(gpu), "gpu_peak": _r(gpu_max),
            })
        return result


def _r(value):
    return None if value is None else round(value, 1)
