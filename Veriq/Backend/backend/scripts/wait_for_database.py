"""Block until the configured database accepts a connection (max ~60s)."""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.database import DATABASE_URL  # noqa: E402


def main() -> int:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("Database is ready.")
            return 0
        except Exception:
            time.sleep(2)
    print("Database did not become ready within 60 seconds.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
