"""Independent authorization: does not open or migrate the original P8 ledger."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from agentguard_bench.live import BudgetExhausted, LiveBudget

AUTHORIZATION = "P8-enhanced-20261022-180-attempts-512-output"


class ExperimentBudget(LiveBudget):
    max_output_tokens = 512

    def __init__(self, directory, *, limit=180):
        if type(limit) is not int or not 1 <= limit <= 180:
            raise ValueError("Authorized limit must be 1..180")
        super().__init__(directory)
        self.limit = limit
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS grant_config (id INTEGER PRIMARY KEY, value TEXT)"
            )
            config = json.dumps([AUTHORIZATION, limit, self.max_output_tokens])
            existing = db.execute("SELECT value FROM grant_config WHERE id=1").fetchone()
            foreign = db.execute(
                "SELECT COUNT(*) FROM requests WHERE authorization!=?", (AUTHORIZATION,)
            ).fetchone()[0]
            if foreign or (existing and existing[0] != config):
                raise ValueError("Existing authorization configuration mismatch")
            db.execute("INSERT OR IGNORE INTO grant_config VALUES (1,?)", (config,))

    def reserve(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] >= self.limit:
                raise BudgetExhausted("Enhanced authorization exhausted")
            metadata = {"started_at": datetime.now(UTC).isoformat(), "status": "reserved"}
            return db.execute(
                "INSERT INTO requests(authorization,metadata) VALUES (?,?)",
                (AUTHORIZATION, json.dumps(metadata)),
            ).lastrowid

    def finish(self, request_id, **kwargs):
        started = next(r.get("started_at") for r in self.records() if r["attempt"] == request_id)
        super().finish(request_id, **kwargs)
        with closing(sqlite3.connect(self.path)) as db, db:
            data = json.loads(
                db.execute("SELECT metadata FROM requests WHERE id=?", (request_id,)).fetchone()[0]
            )
            data["started_at"] = started
            db.execute("UPDATE requests SET metadata=? WHERE id=?", (json.dumps(data), request_id))
