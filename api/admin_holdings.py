"""Admin-only position changes. Preview is read-only; apply requires explicit confirmation."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.feedback import require_admin
from api.submissions import connection
from src.model import trades

router = APIRouter(prefix='/api/admin/holdings')


class ChangeSet(BaseModel):
    changes: list[dict] = Field(max_length=100)
    note: str = Field(default='', max_length=300)


class ApplySet(ChangeSet):
    confirm: bool = False


def _funds():
    from api.main import CFG
    return CFG['funds']


@router.get('')
def holdings(_admin=Depends(require_admin)):
    with connection() as conn:
        return {'funds': trades.overview(conn, _funds()), 'sectors': trades.SECTORS, 'capClasses': trades.CAP_CLASSES}


@router.post('/preview')
def preview(payload: ChangeSet, _admin=Depends(require_admin)):
    with connection() as conn:
        try:
            return trades.run(conn, payload.changes, _funds())
        except trades.TradeError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.post('/apply')
def apply(payload: ApplySet, admin=Depends(require_admin)):
    if not payload.confirm:
        raise HTTPException(400, 'Changes must be explicitly confirmed')
    with connection() as conn:
        try:
            return trades.run(conn, payload.changes, _funds(),
                              payload.note, str(admin.get('id') or ''), write=True)
        except trades.TradeError as exc:
            raise HTTPException(422, str(exc)) from exc
