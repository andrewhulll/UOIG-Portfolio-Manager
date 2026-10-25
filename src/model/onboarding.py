"""First-session welcome tour: remembers, per user, that it has been shown."""
from src.model.submissions import execute, now, rows

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_onboarding (
    user_id TEXT PRIMARY KEY, shown_at TEXT NOT NULL, reason TEXT
)
"""
BACKFILL_KEY = '__backfill__'  # marker row: existing members were marked as already seen


def ensure_schema(conn):
    conn.execute(SCHEMA)
    conn.commit()


def _claim(conn, user_id, reason):
    """Insert the row if absent. True only for the one caller that created it."""
    changed = execute(conn, '''INSERT INTO user_onboarding (user_id, shown_at, reason)
        VALUES (?, ?, ?) ON CONFLICT (user_id) DO NOTHING''', (user_id, now().isoformat(), reason))
    conn.commit()
    return changed.rowcount == 1


def ensure_backfilled(conn, member_ids):
    """On first use, mark everyone who is already a member as having seen the tour,
    so only people who join afterwards get it. Runs once."""
    if rows(conn, 'SELECT 1 FROM user_onboarding WHERE user_id=?', (BACKFILL_KEY,)):
        return
    for uid in member_ids:
        _claim(conn, uid, 'existing member')
    _claim(conn, BACKFILL_KEY, 'backfill complete')


def should_show(conn, user_id):
    """Atomically decide whether to open the tour. Only the first call ever returns True."""
    return _claim(conn, user_id, 'first session')
