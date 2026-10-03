# Real-time messages: what's in place and how to go further

## What happens today

An open request page checks the server every 10 seconds while the tab is visible:

- Customer page: `GET /api/v1/garage/requests/<id>/updates/?after=<last message id>`
- Staff page: `GET /api/v1/manage/requests/<id>/updates/?after=<last message id>`

The response holds any newer messages and the request's `updated_at`. New messages are
appended to the thread. If `updated_at` moved (status, appointment, invoice), the page
reloads the request. Messages the viewer sees this way are marked read.

| Piece | Where |
|-------|-------|
| Endpoints | `backend/apps/intake/views.py`: `_updates`, `MyRequestUpdatesView`, `StaffRequestUpdatesView` |
| Rate limit | `garage_poll` in `config/settings/base.py` (1200/hour per customer) |
| Polling loop | `frontend/src/composables/useLiveUpdates.ts` |
| Used by | `CustomerRequestView.vue`, `StaffRequestView.vue` |

Hidden tabs don't poll, and coming back to the tab checks right away. If the server
fails or rate-limits, the wait doubles, up to 2 minutes. A reply shows up within about
10 seconds. Tune it with `POLL_INTERVAL_MS`.

**Cost:** one small query per open page every 10 seconds. With 50 pages open at
once that's 5 requests a second, which a single small server handles easily. This
covers a one-person shop for a long time.

## Why not webhooks?

Webhooks are one server calling another server's URL when something happens (Stripe
notifying your backend of a payment, for example). A browser has no URL a server can
call, so webhooks can't update a page someone has open. The two ways to *push* to a
browser are Server-Sent Events and WebSockets.

## Option 1: Server-Sent Events (SSE)

The browser opens one long-lived HTTP request (`EventSource`) and the server writes an
event whenever there's news. It only goes server → browser, which fits here: sending a
message stays a normal POST.

What it takes:

1. **An async server.** Run Django under ASGI (`uvicorn config.asgi:application` or
   `daphne`) instead of a WSGI server like gunicorn. Under WSGI, each open stream ties up
   a whole worker.
2. **A way to tell the stream about new messages.** Use Postgres `LISTEN/NOTIFY` (if
   you're on Postgres) or Redis pub/sub. Whatever saves a `RequestMessage` (or changes a
   request) publishes `{request_id}`; each open stream for that request wakes up and
   sends the new rows.
3. **An endpoint** like `GET /api/v1/garage/requests/<id>/events/` that returns a
   `StreamingHttpResponse` with `text/event-stream`, checks permissions exactly like
   `_updates`, and sends a comment line every ~20s to keep proxies from closing it.
4. **Auth.** `EventSource` can't send an `Authorization` header. Either issue a
   short-lived, single-request token from a normal authed call and pass it as
   `?token=`, or use the `fetch` streaming API with headers (e.g. `@microsoft/fetch-event-source`).
5. **Frontend.** In `useLiveUpdates.ts`, open the stream and fall back to the existing
   polling when it errors. The views don't need to change.
6. **Hosting.** Turn off response buffering for that path (`X-Accel-Buffering: no` on
   nginx) and allow long timeouts.

Effort: about a day, plus picking and running Redis or Postgres `NOTIFY`.

## Option 2: WebSockets (Django Channels)

Two-way, so messages could also be *sent* over the socket, and it opens the door to
"typing…" or online indicators.

What it takes: `channels` and `channels-redis`, a Redis server, an ASGI server, a
`consumers.py` with group-per-request (`request_<id>`), authenticating the socket
(token in the first message or the query string), `group_send` from the same places
that save messages, and a reconnecting client in the frontend. Your host must support
WebSocket upgrades.

Effort: 1–3 days, plus Redis to run and monitor. More moving parts than SSE for little
gain at this scale.

## Recommendation

Stay on polling until it's a real problem. If you want replies to land faster first,
lower `POLL_INTERVAL_MS` to 5 seconds and raise `garage_poll` to match. If you outgrow
that, go with SSE (option 1): it reuses the same permission checks and the same
frontend composable. Keep polling as the fallback.

Either way, email is still how people learn about a reply when the page isn't open. A
later step could be browser push notifications (the Web Push API with a service
worker), which reach a customer even with the site closed. That's a separate project,
mostly on the frontend, plus storing push subscriptions per user.
