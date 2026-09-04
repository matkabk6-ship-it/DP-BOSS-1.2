# DP BOSS

DP BOSS is a self-contained, mobile-first social platform with a server-side SQLite database. It intentionally creates no sample users, posts, messages, notifications, analytics, or payment results.

## Run locally

1. Copy `.env.example` to `.env`, set `SESSION_SECRET`, and (optionally) set a strong `ADMIN_PASSWORD` for the configured `ADMIN_EMAIL` before the first run.
2. Run `python3 server.py` and open `http://localhost:8000`.
3. The database is created at `data/dpboss.db`; back it up with your managed database backup process in production.

## Production integration boundaries

This initial foundation has working authentication, a persisted feed, post creation/deletion, likes, comments, follows, blocks, reports, notifications, and a role-protected analytics overview. Its normalized schema prepares stories, saved posts, conversations/messages, subscriptions, and audit logs. Media, email/password-reset delivery, real-time transport, payment checkout/webhooks, account settings, and their UI flows are deliberately not exposed until their production services are configured: the UI does not show a payment-success state and never activates VIP from the browser. Put TLS, a managed database, object storage/signed upload service, mail sender, real-time service, and a payment provider webhook in front of this service before public deployment.

## Security notes

Passwords use `scrypt`; session tokens are opaque HttpOnly cookies whose server-side SHA-256 hashes are persisted. All mutation APIs require JSON requests and authenticated sessions, with endpoint rate limiting. Feed and interaction lookups enforce blocks and post visibility. Use HTTPS, a random deployment `SESSION_SECRET`, and add `Secure` to cookies through the production reverse proxy/deployment configuration.

## API overview

`POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`; `GET /api/feed`; `POST /api/posts`; `POST /api/posts/:id/like`; `POST /api/posts/:id/comments`; `POST /api/users/:username/follow`; `POST /api/users/:username/block`; `POST /api/report`; `GET /api/messages`; `GET /api/notifications`; and `GET /api/admin/overview` for staff roles.
