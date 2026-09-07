"""Role-scoped weekly news routes, kept separate from the market-data API."""
from contextlib import contextmanager
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.auth import organization, sessions, workos_client as wc
from src.model import submissions as store

router = APIRouter(prefix='/api')
ANALYST_ROLES = {'analyst', 'member'}


def identity(request: Request):
    if wc.auth_disabled():
        return {'id': 'dev', 'role': wc.admin_role()}
    user, role = sessions.user_payload(getattr(request.state, 'user', None))
    if not user.get('id'):
        raise HTTPException(401, 'not authenticated')
    return {**user, 'role': role}


def directory():
    from api.main import _dev_directory
    try:
        return (_dev_directory() if wc.auth_disabled() else organization.list_members())['members']
    except organization.OrganizationError as exc:
        raise HTTPException(502, str(exc)) from exc


@contextmanager
def connection():
    from api.main import _conn
    conn = _conn()
    try:
        store.ensure_schema(conn)
        yield conn
    finally:
        conn.close()


def week_context(week=None):
    try:
        return store.week_info(week)
    except ValueError as exc:
        raise HTTPException(422, 'week must be a Monday in YYYY-MM-DD format') from exc


def require_analyst(user):
    if user['role'] not in ANALYST_ROLES:
        raise HTTPException(403, 'Only analysts can flag news and submit digests')


def member_for(user, members):
    member = next((m for m in members if m['id'] == user['id']), None)
    if member is None:
        raise HTTPException(403, 'Active directory membership is required')
    return member


def analyst_sector(user, members, sector, ticker=None):
    require_analyst(user)
    member = member_for(user, members)
    sectors = member.get('sectors') or []
    if not sector and ticker:
        matching = list({c['sector'] for c in member.get('coverage', []) if c['ticker'] == ticker})
        if len(matching) == 1:
            sector = matching[0]
    if not sector and len(sectors) == 1:
        sector = sectors[0]
    if not sector or sector not in sectors:
        raise HTTPException(403, 'Choose one of your assigned sectors')
    return sector


def lead_sectors(user, members, sector=None):
    if wc.is_admin(user['role']):
        return [sector] if sector else None
    if user['role'] != 'sector-leader':
        raise HTTPException(403, 'Only sector leaders and admins can read submissions')
    allowed = member_for(user, members).get('sectors') or []
    if sector and sector not in allowed:
        raise HTTPException(403, 'This sector is outside your assignments')
    return [sector] if sector else allowed


class FlagBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    title: str = Field(min_length=1, max_length=500)
    note: str = Field(default='', max_length=5000)
    ticker: str | None = Field(default=None, max_length=12, pattern=r'^[A-Za-z0-9.^=\-]+$')
    url: str | None = Field(default=None, max_length=2048)
    sector: str | None = Field(default=None, max_length=40)

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        if value is not None:
            try:
                parsed = urlsplit(value)
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or any(c.isspace() for c in value):
                    raise ValueError('Use an http or https news link')
            except ValueError:
                raise ValueError('Use an http or https news link') from None
        return value


class SubmitBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    sector: str | None = Field(default=None, max_length=40)


def editable(draft):
    if draft['status'] != 'draft':
        raise HTTPException(409, 'This submission has been sent and is read-only')


@router.get('/flags/mine')
def mine(week: str | None = None, user=Depends(identity)):
    ctx = week_context(week)
    members = directory()
    member = member_for(user, members)
    with connection() as conn:
        flags = store.rows(conn, 'SELECT * FROM news_flags WHERE user_id=? AND week_of=? ORDER BY created_at, id', (user['id'], ctx['week']))
        submissions = store.rows(conn, 'SELECT * FROM submissions WHERE user_id=? AND week_of=? ORDER BY sector', (user['id'], ctx['week']))
    return {**ctx, 'flags': flags, 'submissions': submissions,
            'sectors': member.get('sectors') or [], 'coverage': member.get('coverage') or []}


@router.post('/flags')
def create_flag(body: FlagBody, user=Depends(identity)):
    sector = analyst_sector(user, directory(), body.sector, (body.ticker or '').upper())
    week = week_context()['week']
    flag = {'id': uuid4().hex, 'user_id': user['id'], 'sector': sector,
            'ticker': body.ticker.upper() if body.ticker else None, 'url': body.url,
            'title': body.title, 'note': body.note, 'week_of': week, 'created_at': store.now().isoformat()}
    with connection() as conn, store.locked_draft(conn, user['id'], sector, week) as draft:
        editable(draft)
        if body.url:
            existing = store.rows(conn, 'SELECT * FROM news_flags WHERE user_id=? AND sector=? AND week_of=? AND url=?', (user['id'], sector, week, body.url))
            if existing:
                return existing[0]
        store.execute(conn, 'INSERT INTO news_flags (id,user_id,sector,ticker,url,title,note,week_of,created_at) VALUES (?,?,?,?,?,?,?,?,?)', tuple(flag.values()))
    return flag


def owned_flag(conn, flag_id, user):
    require_analyst(user)
    flags = store.rows(conn, 'SELECT * FROM news_flags WHERE id=? AND user_id=?', (flag_id, user['id']))
    if not flags:
        raise HTTPException(404, 'Flag not found')
    flag = flags[0]
    if flag['week_of'] != week_context()['week']:
        raise HTTPException(409, 'Past weeks are read-only')
    return flag


@router.patch('/flags/{flag_id}')
def update_flag(flag_id: str, body: FlagBody, user=Depends(identity)):
    with connection() as conn:
        flag = owned_flag(conn, flag_id, user)
        analyst_sector(user, directory(), flag['sector'])
        if body.sector and body.sector != flag['sector']:
            raise HTTPException(422, 'Remove and recreate an item to change its sector')
        with store.locked_draft(conn, user['id'], flag['sector'], flag['week_of']) as draft:
            editable(draft)
            owned_flag(conn, flag_id, user)  # May have been removed while waiting for the lock.
            if body.url:
                duplicate = store.rows(conn, '''SELECT id FROM news_flags
                    WHERE user_id=? AND sector=? AND week_of=? AND url=? AND id<>?''',
                    (user['id'], flag['sector'], flag['week_of'], body.url, flag_id))
                if duplicate:
                    raise HTTPException(409, 'This article is already in the draft')
            store.execute(conn, 'UPDATE news_flags SET title=?, note=?, ticker=?, url=? WHERE id=?',
                          (body.title, body.note, body.ticker.upper() if body.ticker else None, body.url, flag_id))
            return store.rows(conn, 'SELECT * FROM news_flags WHERE id=?', (flag_id,))[0]


@router.delete('/flags/{flag_id}')
def delete_flag(flag_id: str, user=Depends(identity)):
    with connection() as conn:
        flag = owned_flag(conn, flag_id, user)
        analyst_sector(user, directory(), flag['sector'])
        with store.locked_draft(conn, user['id'], flag['sector'], flag['week_of']) as draft:
            editable(draft)
            owned_flag(conn, flag_id, user)
            store.execute(conn, 'DELETE FROM news_flags WHERE id=?', (flag_id,))
    return {'ok': True}


@router.post('/submissions')
def submit(body: SubmitBody, user=Depends(identity)):
    members = directory()
    sector = analyst_sector(user, members, body.sector)
    week = week_context()['week']
    with connection() as conn, store.locked_draft(conn, user['id'], sector, week) as draft:
        if draft['status'] != 'draft':
            return {**draft, 'items': store.items(conn, draft['id'])}
        flags = store.rows(conn, 'SELECT * FROM news_flags WHERE user_id=? AND sector=? AND week_of=? ORDER BY created_at, id', (user['id'], sector, week))
        if not flags:
            raise HTTPException(422, 'Add at least one news item or summary before submitting')
        recipients = {m['id'] for m in members if m['role'] == 'sector-leader'
                      and sector in m.get('sectors', [])}
        if not recipients:
            raise HTTPException(422, 'No sector leader is assigned to this sector. Ask an admin to assign one.')
        submitted_at = store.now().isoformat()
        for flag in flags:
            store.execute(conn, 'INSERT INTO submission_items (submission_id,flag_id) VALUES (?,?)', (draft['id'], flag['id']))
        for recipient in sorted(recipients):
            store.execute(conn, 'INSERT INTO inbox_messages (id,submission_id,recipient_id,kind,created_at) VALUES (?,?,?,?,?)',
                          (uuid4().hex, draft['id'], recipient, 'submission', submitted_at))
        store.execute(conn, "UPDATE submissions SET status='submitted', submitted_at=? WHERE id=?", (submitted_at, draft['id']))
        return {**draft, 'status': 'submitted', 'submitted_at': submitted_at, 'items': flags}


@router.get('/submissions')
def queue(sector: str | None = None, week: str | None = None, user=Depends(identity)):
    members = directory()
    allowed = lead_sectors(user, members, sector)
    ctx = week_context(week)
    with connection() as conn:
        sql, params = 'SELECT * FROM submissions WHERE week_of=?', [ctx['week']]
        if allowed is not None:
            if not allowed:
                sql += ' AND 1=0'
            else:
                sql += ' AND sector IN (' + ','.join('?' for _ in allowed) + ')'
                params.extend(allowed)
        submissions = store.rows(conn, sql + ' ORDER BY sector, user_id', params)
        sent = [s for s in submissions if s['status'] != 'draft']
        names = {m['id']: m['name'] for m in members}
        for submission in sent:
            submission['analyst'] = names.get(submission['user_id'], 'Former member')
            submission['items'] = store.items(conn, submission['id'])
        by_owner = {(s['user_id'], s['sector']): s for s in sent}
        board = []
        for member in members:
            if member['role'] not in ANALYST_ROLES:
                continue
            for assigned in member.get('sectors', []):
                if allowed is not None and assigned not in allowed:
                    continue
                submission = by_owner.get((member['id'], assigned))
                board.append({'user_id': member['id'], 'analyst': member['name'], 'sector': assigned,
                              'status': submission['status'] if submission else 'pending'})
    return {**ctx, 'submissions': sent, 'board': board,
            'sectors': sorted(set(s for m in members for s in m.get('sectors', [])
                                  if allowed is None or s in allowed))}


@router.post('/submissions/{submission_id}/ack')
def acknowledge(submission_id: str, user=Depends(identity)):
    members = directory()
    allowed = lead_sectors(user, members)
    with connection() as conn:
        found = store.rows(conn, 'SELECT * FROM submissions WHERE id=?', (submission_id,))
        if not found:
            raise HTTPException(404, 'Submission not found')
        submission = found[0]
        if allowed is not None and submission['sector'] not in allowed:
            raise HTTPException(403, 'This sector is outside your assignments')
        if submission['status'] == 'draft':
            raise HTTPException(409, 'This draft has not been submitted')
        timestamp = store.now().isoformat()
        changed = store.execute(conn, "UPDATE submissions SET status='acked', acked_at=?, acked_by=? WHERE id=? AND status='submitted'", (timestamp, user['id'], submission_id))
        if changed.rowcount:
            store.execute(conn, '''INSERT INTO inbox_messages
                (id,submission_id,recipient_id,kind,created_at) VALUES (?,?,?,?,?)''',
                (uuid4().hex, submission_id, submission['user_id'], 'ack', timestamp))
        store.execute(conn, '''UPDATE inbox_messages SET read_at=?
            WHERE submission_id=? AND recipient_id=? AND read_at IS NULL''',
            (timestamp, submission_id, user['id']))
        conn.commit()
        return store.rows(conn, 'SELECT * FROM submissions WHERE id=?', (submission_id,))[0]


@router.get('/inbox')
def inbox(user=Depends(identity)):
    members = directory()
    member = member_for(user, members)
    names = {m['id']: m['name'] for m in members}
    with connection() as conn:
        messages = store.rows(conn, '''SELECT m.id AS message_id, m.kind, m.created_at,
            m.read_at, s.* FROM inbox_messages m JOIN submissions s ON s.id=m.submission_id
            WHERE m.recipient_id=? ORDER BY m.created_at DESC, m.id''', (user['id'],))
        # Losing a sector assignment also revokes access to its received digests.
        messages = [m for m in messages if m['user_id'] == user['id'] or wc.is_admin(user['role'])
                    or (user['role'] == 'sector-leader' and m['sector'] in member.get('sectors', []))]
        for message in messages:
            message['analyst'] = names.get(message['user_id'], 'Former member')
            message['ackedByName'] = names.get(message['acked_by'], 'Sector leader') if message['acked_by'] else None
            message['items'] = store.items(conn, message['id'])
    return {'messages': messages, 'unread': sum(m['read_at'] is None for m in messages)}


@router.post('/inbox/{message_id}/read')
def read_message(message_id: str, user=Depends(identity)):
    with connection() as conn:
        changed = store.execute(conn, '''UPDATE inbox_messages SET read_at=COALESCE(read_at, ?)
            WHERE id=? AND recipient_id=?''', (store.now().isoformat(), message_id, user['id']))
        if not changed.rowcount:
            raise HTTPException(404, 'Message not found')
        conn.commit()
    return {'ok': True}
