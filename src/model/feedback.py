"""User feedback storage, shared by SQLite and Postgres."""
from src.model.submissions import execute, rows

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, user_name TEXT, user_email TEXT,
    body TEXT NOT NULL, page TEXT, created_at TEXT NOT NULL,
    resolved_at TEXT, resolved_by TEXT
);
CREATE INDEX IF NOT EXISTS feedback_created ON feedback(created_at)
"""


def ensure_schema(conn):
    for statement in SCHEMA.split(';'):
        if statement.strip():
            conn.execute(statement)
    conn.commit()


__all__ = ['ensure_schema', 'execute', 'rows']
