# Auth setup — WorkOS (invite-only)

The Investment Terminal is **invite-only** and fully gated by WorkOS AuthKit
(Google OAuth + email/password, with a forgot/set-password reset flow). The
in-app screens are built and hardened; what remains is **WorkOS dashboard
configuration**, which only an admin can do. WorkOS *sends* every auth email
(invitation, password reset, verification) — there is no email code in this
repo — so "the sign-up email" is customized in the WorkOS dashboard using the
draft copy at the bottom of this file.

Do the whole checklist **once per environment**. WorkOS **Staging** and
**Production** are separate: separate API keys, org, redirect URIs, and
branding. Switch environments with the selector in the WorkOS dashboard.

Current state (from a live read of the workspace):
- **Staging** — AuthKit on; Google + Email/Password already enabled; open
  sign-up already off. Missing: the organization and the `pm` role.
- **Production** — AuthKit on, but **Google and Email/Password are OFF**, open
  sign-up is ON, and there is no organization, no `pm` role, and no branding.

---

## Per-environment checklist

1. **AuthKit** — Authentication → AuthKit → ensure it's enabled.
2. **Sign-in methods** — enable **Email + Password** and **Google OAuth** (run
   WorkOS's Google wizard; it walks you through creating a Google Cloud OAuth
   client and pasting the client id/secret into WorkOS). *Production has both
   OFF today — this is the critical fix.*
3. **Redirect URIs** — add the backend callback `/api/auth/callback`:
   - Local/Staging: `http://localhost:5173/api/auth/callback`
   - Production: `https://uoig-portfolio-manager.onrender.com/api/auth/callback`
     *(the backend host — single-container Render. If you split the frontend to
     Vercel later, this stays the backend URL; only `VITE_API_BASE` and
     `FRONTEND_URL`/`CORS_ORIGINS` change.)*
   Set the AuthKit default/return redirect to the frontend origin.
4. **Password-reset redirect** — set it to the app with the `reset` marker (the
   SPA reads `?reset=1&token=…` and shows the set-password form):
   - Local/Staging: `http://localhost:5173/?reset=1`
   - Production: `https://uoig-portfolio-manager.onrender.com/?reset=1`
5. **Disable open self-signup** — turn **Allow sign-ups** OFF. (Production has it
   ON today.) Defense-in-depth; the server already gates on org membership.
6. **Organization (the invite gate)** — Organizations → Create Organization
   `University of Oregon Investment Group`. Copy its `org_…` id and set
   `WORKOS_ORG_ID` for **that environment's** backend. *(Without this the server
   now fails closed and denies every sign-in — by design.)*
7. **Roles** — create a role with slug **`pm`** (matches the app default;
   today only `member`/`admin` exist). Assign yourself the `pm` role so you can
   invite teammates from inside the app.
   *(Alternative: reuse `admin` and set `WORKOS_PM_ROLE=admin` instead.)*
8. **Branding + emails** — Branding: upload the UOIG logo, set brand colors
   (green `#004f27`, gold `#ffc000`), display name `UOIG Investment Terminal`,
   and the sender name + from-address. Then apply the **invitation** and
   **password-reset** email copy below. Theme the AuthKit hosted pages to match.
9. **Password policy** — set both environments the same: **min length 10**,
   **strength 3**, **breached-password check ON** (reconciles today's
   Staging/Production mismatch). The app hints "at least 10 characters".
10. **Invite yourself + teammates** — Organization → Members → Invite (or use
    the in-app profile-menu invite once you're signed in as `pm`).

---

## Backend env vars (per environment)

Set as environment variables, or as git-ignored `*.txt` files at the repo root
(the app reads env first, then the file). All are per-environment.

| Variable | File fallback | What |
|---|---|---|
| `WORKOS_API_KEY` | `workos.key.txt` | Secret API key (`sk_…`) |
| `WORKOS_CLIENT_ID` | `workos.client.txt` | Client id (`client_…`) |
| `WORKOS_COOKIE_PASSWORD` | `workos.cookie.txt` | 32+ char secret; seals the session cookie |
| `WORKOS_ORG_ID` | `workos.org.txt` | The invite-gate org id (`org_…`) |
| `WORKOS_REDIRECT_URI` | — | Defaults to `http://localhost:5173/api/auth/callback`; set to the prod callback in Production |
| `WORKOS_PM_ROLE` | — | Role slug allowed to invite (default `pm`) |
| `UOIG_COOKIE_SECURE` | — | Set `1` in Production (HTTPS) |

Local dev tip: leave `UOIG_AUTH_DISABLED` **unset** to test the real flow; set
`UOIG_AUTH_DISABLED=1` only for UI work without WorkOS.

---

## Email copy to paste into WorkOS

WorkOS renders and sends these; paste this copy into the corresponding template
fields (subject / heading / body / button). Keep it short — WorkOS controls the
surrounding layout and the actual link button.

### Invitation ("sign-up") email
- **Subject:** You're invited to the UOIG Investment Terminal
- **Heading:** You've been invited
- **Body:** You've been invited to the University of Oregon Investment Group's
  Investment Terminal — the desk's live view of the Tall Firs and Alumni Fund
  portfolios. Click below to set up your account. This invitation is personal to
  your email address and expires in 7 days.
- **Button:** Accept your invitation

### Password-reset email (also first-time set-password for invitees)
- **Subject:** Reset your UOIG Investment Terminal password
- **Heading:** Reset your password
- **Body:** We received a request to set a new password for your Investment
  Terminal account. Click below to choose one. If you didn't request this, you
  can safely ignore this email — your password won't change.
- **Button:** Set a new password

### Email verification (only shown if WorkOS requires a code)
- **Subject:** Your UOIG Investment Terminal verification code
- **Body:** Enter this code to verify your email and finish signing in. It
  expires shortly. If you didn't try to sign in, you can ignore this email.
