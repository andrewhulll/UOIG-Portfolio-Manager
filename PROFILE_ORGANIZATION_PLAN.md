# Profile, preferences, and organization implementation plan

## Outcome and scope

Replace the crowded avatar popover with links to My profile, Preferences,
Organization, and Sign out. Add dedicated settings views matching the terminal's
existing dark design. Every active UOIG member can browse teammates and coverage;
only admins manage access. The profile, preference, directory, and admin-invite UI
is implemented. Role, coverage, deactivation, and invitation-lifecycle management
remain later phases. The accompanying script creates the requested WorkOS roster.

## Verified starting point

- `web/src/App.jsx`: `_renderProfileMenu` contains identity, raw role badge, inline
  admin invite form, and logout. Fund selection is stored in browser localStorage.
- `web/src/api.js`: current-user, invitation, password-reset, and logout clients.
- `api/main.py`: `/api/auth/me` returns user, role, canInvite. The invite endpoint
  checks admin, but ordinary authenticated data routes have no role distinctions.
- `src/auth/sessions.py`: membership is checked during sign-in. Sessions can lack
  an organization-scoped role; resolve authoritative membership before introducing
  member management, and test removal/demotion against existing sessions.
- WorkOS UOIG roles inspected: Admin=`admin`, Sector Leader=`sector-leader`,
  Analyst=`member`. README's suggested `analyst` slug differs from actual setup.
  Use verified slugs and display names; do not rename roles during this project.
- Existing app sector key is `Financial`; supplied roster label is `Financials`.
  Use a stable internal sector ID and explicit label mapping.

## Product decisions

1. Users edit their own name, optional bio/graduation year, and preferences. Start
   with provider photo + initials; custom photo upload follows a storage decision.
   Display organization, role, sectors, and coverage as read-only on own profile.
2. All active members see a searchable directory: avatar/name, organization email,
   role, multiple sectors, and covered tickers. Add role/sector filters and member
   details; show a Mock badge for seeded accounts. Exclude inactive users and
   pending invitations from the ordinary directory.
3. Admins can invite, resend/revoke invitations, edit roles and coverage, and
   deactivate membership. Protect the last admin and reject unauthorized requests
   server-side. Deactivate organization membership rather than deleting identity.
4. Sector leaders initially have directory access only. Delegated assignment edits
   are a later feature with explicit sector-lead assignments and server checks.
   Do not infer leadership from list order, names, or coverage.
5. Save default fund (All/Tall Firs/Alumni), chart period, landing page, density,
   text size, and reduced-motion preference per account. Follow OS motion setting
   initially. These preferences never change official benchmark/portfolio settings.
6. Account security shows supported sign-in methods and password management where
   available. Email changes require verified provider flows, not free-form edits.
   Add session list/revocation later after confirming pinned WorkOS SDK support.
7. Shared directory excludes login history, sessions, security details, private
   metadata, and personal phone/address. Pending invites and admin audit history
   are visible only to admins.

## Data model and authority

WorkOS owns identity, organization membership/status, and access roles. Application
DB owns optional profile details, preferences, sector membership, coverage, and
management audit records. Use existing SQLite/Postgres helpers and migrations.

| Proposed table | Key and purpose |
| --- | --- |
| user_profiles | WorkOS user ID PK; bio, graduation year, optional avatar reference |
| user_preferences | WorkOS user ID PK; validated preference fields, version, updated_at |
| organization_sectors | (org_id, sector_id) PK; display name |
| member_sectors | (org_id, user_id, sector_id) PK; multiple sectors per person |
| coverage_assignments | (org_id, user_id, sector_id, source_ticker) unique; optional resolved security ID, term, timestamps |
| organization_audit | org_id, actor, action, target, minimal before/after fields, timestamp |

Avoid duplicating WorkOS passwords or authoritative roles in the application DB.
Scope every assignment and member operation to the authenticated organization;
never trust a client-supplied org ID. Preserve raw tickers independently from a
resolved security so unsupported/historical symbols can still appear in profiles.
`BRK` needs a share-class decision before linking to live quotes. Preserve `CON`
and all other supplied symbols verbatim until ticker resolution is reviewed.

For the mock seed only, WorkOS user metadata stores a mock marker, seed ID,
organization ID, original display name, and serialized sector/ticker assignments.
When building the app, import those assignments idempotently into application
tables keyed by WorkOS user ID + org ID; metadata is not an authorization source.

## Delivery sequence

### 1. Membership and storage foundation

- Add `src/auth/organization.py` for organization-scoped reads/management using
  the existing pinned SDK, plus explicit current membership/role checks.
- Extend `/api/auth/me` with organization summary, role display name, and narrowly
  derived capabilities. Handle Google/password sessions without a role reliably.
- Add schema migrations and repositories for the tables above. Add a bounded
  membership cache, invalidate on local management actions, and handle WorkOS
  membership changes via verified webhooks or a documented short recheck interval.
- Restrict profile PATCH fields so metadata/roles/coverage cannot be mass-assigned.

### 2. Profile and preferences

- Extract avatar/menu into `web/src/profile/`; add ProfilePage, PreferencesPage,
  and reusable settings fields. Keep App.jsx focused on navigation/data context.
- Proposed endpoints: GET/PATCH `/api/profile`, GET/PATCH `/api/preferences`.
- Save identity fields through WorkOS and app-only fields in the DB; report partial
  failures honestly and support retry without claiming all fields were saved.
- Import local fund preference once only when no account preference exists, then
  use account preferences across devices. Clear user-specific state on logout.
- Add visible Save/Cancel, validation, unsaved-change handling, keyboard focus,
  real button elements, Escape-to-close popover, loading/error/success states.

### 3. Directory and coverage

- Proposed endpoints: GET `/api/organization`, GET `/api/organization/members`,
  GET `/api/organization/members/{user_id}`. Paginate WorkOS results fully; filter
  and search consistently across all pages rather than only loaded results.
- Return an allowlisted DTO rather than raw WorkOS user records.
- Build OrganizationPage, MembersTable, and MemberDetails panel. Support multiple
  sector chips and stock links, with a clear unresolved-symbol state.
- Seed the app's coverage tables from the mock metadata; expose members covering
  a stock on its detail page and teammates covering a sector on sector pages.

### 4. Admin management

- Move inline invite form into the Organization page, with explicit role choice
  restricted to known UOIG roles. Show pending/expired invitations separately.
- Proposed admin endpoints: GET/POST invitations; POST invitation resend/revoke;
  PATCH member role; POST member deactivate; PUT member sectors/coverage.
- Every endpoint validates actor membership, target organization, role allowlist,
  and last-admin constraints. Show concrete consequences before removal/demotion.
- Add audit records and refresh directory/session capabilities after changes.
- Define race-safe last-admin protection and session revocation before shipping
  deactivation; coordinate WorkOS and local state with recoverable operations.

### 5. Follow-on features

- Custom avatar upload with validated size/type, private storage, and safe serving.
- Active sessions and sign out everywhere; provider-supported security controls.
- Optional sector-leader coverage delegation, bounded to assigned sectors.
- Research contribution history; notifications/digests only after event delivery
  exists. Add opt-in preferences with supported channels/frequency at that time.

## Validation and release gates

- Backend integration tests: unauthenticated request, other-organization target,
  analyst/admin/leader permissions, raw role `member`, role-less sessions, inactive
  membership, stale session after removal, last admin, invitation lifecycle,
  pagination, provider failures, and forbidden profile-field writes.
- Persistence tests on SQLite and Postgres: multiple sectors, uniqueness,
  preferences isolated per account, repeated mock import creates no duplicates.
- Browser checks: desktop/mobile, keyboard-only navigation, long names/emails,
  no-photo fallback, empty/error states, filters, unresolved ticker, repeated
  names deduplicated, and admin actions hidden and forbidden for ordinary users.
- Run relevant existing auth tests and frontend production build. Release read-only
  directory/profile/preferences first; enable admin mutations after permission and
  revocation checks pass. Keep a feature flag to hide new screens if needed.

## Mock roster policy and runbook

Seed completed and independently verified against WorkOS: 33 mock users, 49
coverage assignments, and active Analyst (`member`) memberships under UOIG.
UOIG now has 35 active members including the 2 pre-existing admins, untouched.
Assignment counts: TMT 13, Consumer 6, Financials 8, Healthcare 10, IME 12.

Source: `data/mock_uoig_roster.json`, transcribed from the supplied table. Deduplicate
exact display names across sectors; keep Jackson B/L and the two named Wills
separate. No invented surnames, photos, biographies, or leadership assignments.

Run `python -m scripts.seed_workos_mock_users` to preview, then add `--apply` to
create users and active UOIG Analyst memberships. Uses configured WorkOS key/org;
checks organization name and Analyst role before writes. All emails follow
`mock.<name>@uoig.example.invalid`; display names end in `(Mock)`, email_verified
is false, no passwords are set, and no invitations or mail endpoints are called.
These are directory fixtures, not login-ready test accounts.

The script reuses only matching seed-marked mock users, refuses unmarked collisions,
checks metadata, verifies each resulting membership, and records IDs in
`.tmp/workos-mock-users-result.json` without secrets. On failure, rerun to resume;
do not automatically delete users to roll back partial progress. Future cleanup
must select exact seed + organization + returned IDs and preview its targets.
Existing real accounts, including any real Andrew Hull account, are not modified.

## References

- [WorkOS users: create fields and metadata](https://workos.com/docs/reference/authkit/user)
- [WorkOS organization memberships](https://workos.com/docs/reference/authkit/organization-membership)
- [WorkOS organization role listing](https://workos.com/docs/reference/roles/custom-role)
