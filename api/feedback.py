"""Platform feedback: anyone signed in can submit; admins review and resolve."""
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.submissions import connection, identity
from src.auth import workos_client as wc
from src.model import feedback as store
from src.model.submissions import now

router = APIRouter(prefix='/api/feedback')


class FeedbackIn(BaseModel):
    body: str = Field(max_length=4000)
    page: str | None = Field(default=None, max_length=200)

    @field_validator('body')
    @classmethod
    def not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Feedback cannot be empty')
        return value


class ResolveIn(BaseModel):
    resolved: bool


def require_admin(user=Depends(identity)):
    if not wc.is_admin(user['role']):
        raise HTTPException(403, 'admin only')
    return user


@router.post('')
def submit(payload: FeedbackIn, user=Depends(identity)):
    fid = uuid4().hex
    with connection() as conn:
        store.ensure_schema(conn)
        store.execute(conn, '''INSERT INTO feedback
            (id, user_id, user_name, user_email, body, page, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (fid, user['id'], user.get('name'), user.get('email'), payload.body,
             payload.page, now().isoformat()))
        conn.commit()
    return {'ok': True, 'id': fid}


@router.get('')
def list_feedback(_admin=Depends(require_admin)):
    with connection() as conn:
        store.ensure_schema(conn)
        items = store.rows(conn, 'SELECT * FROM feedback ORDER BY created_at DESC, id')
    return {'items': items, 'open': sum(i['resolved_at'] is None for i in items)}


@router.patch('/{feedback_id}')
def resolve(feedback_id: str, payload: ResolveIn, admin=Depends(require_admin)):
    with connection() as conn:
        store.ensure_schema(conn)
        done = (now().isoformat(), admin['id']) if payload.resolved else (None, None)
        changed = store.execute(conn, 'UPDATE feedback SET resolved_at=?, resolved_by=? WHERE id=?',
                                (*done, feedback_id))
        if not changed.rowcount:
            raise HTTPException(404, 'Feedback not found')
        conn.commit()
    return {'ok': True, 'resolvedAt': done[0]}
