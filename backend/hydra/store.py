"""SQLite persistence for replicas, provider history and the event timeline."""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import asdict
from typing import Dict, List

from .models import Replica

SCHEMA = """
CREATE TABLE IF NOT EXISTS replicas (
    id TEXT PRIMARY KEY, dseq TEXT, provider TEXT, uri TEXT, price REAL,
    status TEXT, strikes INTEGER, created_at REAL, first_failed_at REAL
);
CREATE TABLE IF NOT EXISTS providers (
    address TEXT PRIMARY KEY, probes INTEGER DEFAULT 0, successes INTEGER DEFAULT 0,
    failures INTEGER DEFAULT 0, price REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, message TEXT
);
"""


class Store:
    def __init__(self, path: str = ":memory:"):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def save_replica(self, replica: Replica) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO replicas VALUES "
                "(:id, :dseq, :provider, :uri, :price, :status, :strikes, :created_at, :first_failed_at)",
                asdict(replica),
            )

    def delete_replica(self, replica_id: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM replicas WHERE id = ?", (replica_id,))

    def load_replicas(self) -> List[Replica]:
        with self.lock:
            return [Replica(**dict(row)) for row in self.db.execute("SELECT * FROM replicas")]

    def record_probe(self, provider: str, ok: bool) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO providers (address) VALUES (?)", (provider,))
            self.db.execute(
                "UPDATE providers SET probes = probes + 1, successes = successes + ? WHERE address = ?",
                (int(ok), provider),
            )

    def record_failure(self, provider: str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO providers (address) VALUES (?)", (provider,))
            self.db.execute("UPDATE providers SET failures = failures + 1 WHERE address = ?", (provider,))

    def record_price(self, provider: str, price: float) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO providers (address) VALUES (?)", (provider,))
            self.db.execute("UPDATE providers SET price = ? WHERE address = ?", (price, provider))

    def providers(self) -> Dict[str, dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM providers")
            return {row["address"]: dict(row) for row in rows}

    def add_event(self, kind: str, message: str) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO events (ts, kind, message) VALUES (?, ?, ?)", (time.time(), kind, message)
            )

    def events(self, limit: int = 50) -> List[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT ts, kind, message FROM events ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [dict(row) for row in rows]
