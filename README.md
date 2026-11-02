# Hotel Room Booking System

Django + Django REST Framework. Manage rooms and book a room by features
(number of beds + view) for a time period; the system picks a free matching
room automatically and never allows overlapping bookings on a room.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
python manage.py test        # run the test suite
```

Uses SQLite by default. No other configuration is needed. Optional env vars:
`DJANGO_SECRET_KEY`, `DJANGO_DEBUG` (`1`/`0`), `DJANGO_ALLOWED_HOSTS`.

## API

Browsable at `http://localhost:8000/api/`.

### Rooms - `/api/rooms/`
`GET` (paginated list), `POST`, `GET/PUT/PATCH/DELETE /api/rooms/<id>/`

```json
{"label": "101", "number_of_beds": 2, "view": "sea"}
```
`view` is one of `sea`, `mountain`, `yard`. `number_of_beds` is 1-5, `label` is unique.
Deleting a room that has bookings returns `409`. Changing `number_of_beds` or `view`
of a room that has upcoming or ongoing confirmed bookings also returns `409` (cancel
them first); renaming the label is always allowed.

### Availability - `GET /api/rooms/available/`
Query params: `check_in`, `check_out` (required), `number_of_beds`, `view` (optional).
```
GET /api/rooms/available/?check_in=2026-12-01T14:00:00Z&check_out=2026-12-03T11:00:00Z&view=sea
```
Returns the (paginated) rooms with no confirmed booking overlapping the period.
URL-encode `+` in offsets as `%2B`, or use `Z`.

### Book a room - `POST /api/bookings/`
```json
{
  "user_id": 42,
  "number_of_beds": 2,
  "view": "sea",
  "check_in": "2026-12-01T14:00:00Z",
  "check_out": "2026-12-03T11:00:00Z"
}
```
- `201` with the booking and the assigned room.
- `409` if no room matches the features or all matching rooms are busy in that period.
- `400` for invalid input (e.g. `check_in` in the past, `check_out <= check_in`, bad view, beds outside 1-5).

### Cancel - `POST /api/bookings/<id>/cancel/`
Returns the booking with `status: "cancelled"`. `409` if it is already cancelled or has
already started; `404` if unknown. Cancelled bookings are kept (soft cancel) but no longer
block the room.

### Reschedule - `POST /api/bookings/<id>/reschedule/`
```json
{"check_in": "2026-12-05T14:00:00Z", "check_out": "2026-12-07T11:00:00Z"}
```
Creates a **new** booking for the new dates and marks the old one `rescheduled`. The new
booking has `rescheduled_from` (old id) and the old one shows `rescheduled_to` (new id).
The same room is used if free, otherwise another room with the same features. `201` with
the new booking; `409` if nothing is free for the new dates (the original booking is left
unchanged) or if the booking is cancelled, already rescheduled or already started;
`400` for invalid dates; `404` if unknown.

Also available: `GET /api/bookings/` (optional `?user_id=`, `?status=confirmed|cancelled|rescheduled`)
and `GET /api/bookings/<id>/`.

Example:
```bash
curl -X POST localhost:8000/api/rooms/ -H 'Content-Type: application/json' \
  -d '{"label":"101","number_of_beds":2,"view":"sea"}'
curl -X POST localhost:8000/api/bookings/ -H 'Content-Type: application/json' \
  -d '{"user_id":1,"number_of_beds":2,"view":"sea","check_in":"2026-12-01T14:00:00Z","check_out":"2026-12-03T11:00:00Z"}'
```

## Technical decisions and assumptions

- **Overlap rule:** periods are half-open `[check_in, check_out)`. Two bookings
  conflict iff `existing.check_in < new.check_out AND existing.check_out > new.check_in`,
  so a guest can check in exactly when the previous one checks out.
- **Room selection:** among matching rooms that are free, the one with the lowest id
  is chosen (deterministic, easy to test). Swapping in a smarter strategy only
  touches `hotel/services.py`.
- **Concurrency:** booking runs in a transaction that locks all rooms matching the
  requested features (`SELECT ... FOR UPDATE`, ordered by id) before checking overlaps,
  so two simultaneous requests cannot double-book a room. On SQLite row locks are
  no-ops but writers are serialized anyway.
- **Layering:** views handle HTTP, serializers validate input, `services.book_room`
  holds the business logic.
- **Cancellation:** a soft cancel (`status` + `cancelled_at`) keeps history and audit trail;
  every overlap/availability query only considers `confirmed` bookings (cancelled and
  rescheduled ones never block a room). Cancelling is only
  allowed before check-in. The row is locked while cancelling so it can't race itself.
- **Rescheduling:** bookings are treated as immutable records, so a reschedule creates a new
  booking linked to the old one through a `OneToOneField` (`rescheduled_from`) instead of
  editing dates in place. The old booking gets its own status, `rescheduled`, so reports can
  tell it apart from a real cancellation. The one-to-one link means a booking can be
  replaced only once (history is a chain, never a tree). It runs in one transaction: the
  old booking's own period is ignored in the overlap check (so overlapping moves work), the
  same room is tried first, then the other matching rooms, and if none is free everything
  rolls back and the original stays confirmed. Like cancellation, only allowed before check-in.
- **Past check-ins:** rejected with `400` for bookings and availability searches
  (`check_in` earlier than "now"); input validation lives in the serializers.
- **Editing rooms:** beds/view changes are refused (`409`) while a confirmed booking has
  `check_out` in the future, since the guest booked those features. The room row is locked
  during the update so a concurrent booking can't slip in between the check and the save.
- **Data integrity:** DB check constraints for beds in 1-5 and `check_out > check_in`;
  `Booking.room` uses `PROTECT` so rooms with history can't be deleted (API returns 409).
- **`user_id`:** user management is out of scope, so it is a positive integer on the
  booking with no foreign key. Changing it to a FK or string is a one-line model change.
- **Timezones:** `USE_TZ=True`; datetimes should include an offset (naive values are
  interpreted as UTC).