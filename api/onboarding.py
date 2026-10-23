"""First-session welcome tour. The server decides, once per user, so it never reopens."""
from fastapi import APIRouter, Depends, HTTPException

from api import submissions as subs
from api.submissions import connection, identity
from src.model import onboarding as store

router = APIRouter(prefix='/api/onboarding')


@router.post('/start')
def start(user=Depends(identity)):
    """Returns {show: true} exactly once for a new user, and records that it was shown."""
    with connection() as conn:
        store.ensure_schema(conn)
        try:
            members = [m['id'] for m in subs.directory()]
        except HTTPException:
            return {'show': False}  # can't tell who is new right now; never guess
        store.ensure_backfilled(conn, members)
        return {'show': store.should_show(conn, user['id'])}
