"""Weekly news workflow storage, shared by SQLite and Postgres."""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.model import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS news_flags (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, sector TEXT NOT NULL,
    ticker TEXT, url TEXT, title TEXT NOT NULL, note TEXT NOT NULL,
    week_of TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, sector TEXT NOT NULL,
    week_of TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'submitted', 'acked')),
    submitted_at TEXT, acked_at TEXT, acked_by TEXT,
    UNIQUE (user_id, sector, week_of)
);
CREATE TABLE IF NOT EXISTS submission_items (
    submission_id TEXT NOT NULL REFERENCES submissions(id),
    flag_id TEXT NOT NULL REFERENCES news_flags(id),
    PRIMARY KEY (submission_id, flag_id)
);
CREATE TABLE IF NOT EXISTS inbox_messages (
    id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id),
    recipient_id TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('submission', 'ack')),
    created_at TEXT NOT NULL, read_at TEXT,
    UNIQUE (submission_id, recipient_id, kind)
);
CREATE INDEX IF NOT EXISTS inbox_recipient ON inbox_messages(recipient_id, created_at);
CREATE INDEX IF NOT EXISTS news_flags_owner_week ON news_flags(user_id, week_of);
CREATE INDEX IF NOT EXISTS submissions_sector_week ON submissions(sector, week_of);
"""


def ensure_schema(conn):
    for statement in SCHEMA.split(';'):
        if statement.strip():
            conn.execute(statement)
    conn.commit()


def now():
    return datetime.now(timezone.utc)


def week_info(week=None, instant=None):
    local = (instant or now()).astimezone(ZoneInfo('America/Los_Angeles'))
    current = local.date() - timedelta(days=local.weekday())
    monday = date.fromisoformat(week) if week else current
    if week and week != monday.isoformat():
        raise ValueError('week must use YYYY-MM-DD format')
    if monday.weekday() != 0:
        raise ValueError('week must be a Monday in YYYY-MM-DD format')
    due = datetime.combine(monday + timedelta(days=3), time(17), local.tzinfo)
    return {'week': monday.isoformat(), 'currentWeek': current.isoformat(),
            'dueAt': due.isoformat()}


def rows(conn, sql, params=()):
    cur = conn.execute(db.q(conn, sql), params)
    names = [column[0] for column in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def execute(conn, sql, params=()):
    return conn.execute(db.q(conn, sql), params)


@contextmanager
def locked_draft(conn, uid, sector, week):
    """Serialize edits and submit across processes, not just HTTP workers.

    Create the draft durably first so retries retain their submission ID.
    Postgres locks this draft row; SQLite takes its database write lock.
    """
    execute(conn, '''INSERT INTO submissions (id, user_id, sector, week_of)
        VALUES (?, ?, ?, ?) ON CONFLICT (user_id, sector, week_of) DO NOTHING''',
        (uuid4().hex, uid, sector, week))
    conn.commit()
    try:
        if not db.is_pg(conn):
            conn.execute('BEGIN IMMEDIATE')
        suffix = ' FOR UPDATE' if db.is_pg(conn) else ''
        draft = rows(conn, '''SELECT * FROM submissions
            WHERE user_id=? AND sector=? AND week_of=?''' + suffix,
            (uid, sector, week))[0]
        yield draft
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def items(conn, submission_id):
    return rows(conn, '''SELECT f.* FROM news_flags f JOIN submission_items i
        ON i.flag_id=f.id WHERE i.submission_id=? ORDER BY f.created_at, f.id''',
        (submission_id,))
