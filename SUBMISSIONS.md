# Weekly sector updates

Issue #98 uses **in-app inbox delivery**. It requires no email provider or secrets.

Analysts (`member` or `analyst` WorkOS roles) flag articles from a stock's News tab,
add notes, or write freeform summaries under **My Coverage → This week's submission**.
Members covering multiple sectors choose a separate draft for each sector.
Drafts can be edited or removed until submitted. The weekly deadline is Thursday
at 5:00pm America/Los_Angeles time, including daylight saving time. Late submissions
remain available until the next Monday; previous weeks are available read-only.

**Submit to sector lead** resolves every active directory member whose **sector
leadership** assignment includes that sector and creates a message in each one's
**Inbox**. Sector leadership is an explicit admin-assigned list per member (set
from Organization → member detail → Sector leadership), independent of both
their org role — an admin can also be assigned to lead a sector alongside a
dedicated Sector Leader — and their own ticker coverage, so a leader doesn't
need a personal stock assignment to be routed a sector's digests.
If no lead is assigned, the draft stays editable and the app explains the problem.
Saving the submitted digest, its items, and its inbox messages is atomic.
Repeated or concurrent submit requests reuse the same submission. Submitted items
cannot be edited or removed through the API.

Every member has an **Inbox**. Leaders can mark messages read and explicitly
acknowledge a submission. Acknowledgement sends one inbox notification back to the
analyst and updates the saved submission. Reading and acknowledgement are separate
actions. The first acknowledgement is retained when multiple leads review a digest.
Open inboxes and drafts refresh every 30 seconds and have a manual Refresh button.

Leaders and admins also have **Inbox → Sector submissions**, with a per-analyst
submitted/pending board, sector filter, weekly history, and submitted item lists.
Anyone with a sector leadership assignment can only read and acknowledge those
sectors. Admins can review every sector regardless of their own assignments. The
backend gets roles and sector leadership from the authenticated WorkOS session
and the directory; client-supplied identities are rejected.
Removing a lead's sector assignment also removes access to that sector's old digests.

Storage uses the existing SQLite/Postgres connection and placeholder adapter.
`news_flags`, `submissions`, `submission_items`, and `inbox_messages` are created
idempotently on first workflow access and by `create_schema`. Market-data reseeding
preserves these tables. SQLite serializes mutations with `BEGIN IMMEDIATE`;
Postgres locks the user's sector/week draft row. No production DB migration command
or external service is required; the app's DB role needs the same table-creation
permissions used by the existing schema setup.

API routes:

| Route | Access / purpose |
| --- | --- |
| `GET /api/flags/mine?week=YYYY-MM-DD` | Own flags and submission status; week is a Monday |
| `POST /api/flags` | Analyst adds a current-week article or freeform summary |
| `PATCH /api/flags/{id}` | Analyst edits their own draft item |
| `DELETE /api/flags/{id}` | Analyst removes their own draft item |
| `POST /api/submissions` | Analyst submits the sector in `{ "sector": "TMT" }` |
| `GET /api/submissions?sector=&week=` | Lead/admin queue and status board |
| `POST /api/submissions/{id}/ack` | Scoped lead/admin acknowledgement |
| `GET /api/inbox` | Own received messages and unread count |
| `POST /api/inbox/{id}/read` | Mark own message read |

Validation: `pytest tests/test_submissions.py` and `npm --prefix web run build`.
The workflow tests use temporary SQLite databases and fake WorkOS sessions and
directories. They never contact WorkOS or deliver real messages.
