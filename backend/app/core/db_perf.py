from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class DbPerfStats:
    query_count: int = 0
    total_ms: float = 0
    slowest_ms: float = 0
    slowest_statement: str | None = None
    connection_use_count: int = 0
    connection_total_ms: float = 0
    connection_max_ms: float = 0


_db_perf_stats: ContextVar[DbPerfStats | None] = ContextVar("db_perf_stats", default=None)


def reset_db_perf_stats() -> None:
    _db_perf_stats.set(DbPerfStats())


def get_db_perf_stats() -> DbPerfStats | None:
    return _db_perf_stats.get()


def record_db_query(duration_ms: float, statement: str) -> None:
    stats = _db_perf_stats.get()
    if stats is None:
        return
    stats.query_count += 1
    stats.total_ms += duration_ms
    if duration_ms > stats.slowest_ms:
        stats.slowest_ms = duration_ms
        stats.slowest_statement = " ".join(statement.split())[:500]


def record_db_connection_usage(duration_ms: float) -> None:
    stats = _db_perf_stats.get()
    if stats is None:
        return
    stats.connection_use_count += 1
    stats.connection_total_ms += duration_ms
    stats.connection_max_ms = max(stats.connection_max_ms, duration_ms)
