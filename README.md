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
Deleting a room that has bookings returns `409`.

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
- `400` for invalid input (e.g. `check_out <= check_in`, bad view, beds outside 1-5).

Also available: `GET /api/bookings/` (optional `?user_id=`) and `GET /api/bookings/<id>/`.

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
  no-ops but writers are serialized anyway. For PostgreSQL in production, I would
  additionally add an `ExclusionConstraint` on `(room, tstzrange(check_in, check_out))`
  as a database-level safety net. I did not add it so the project runs on SQLite
  with zero setup.
- **Layering:** views handle HTTP, serializers validate input, `services.book_room`
  holds the business logic.
- **Data integrity:** DB check constraints for beds in 1-5 and `check_out > check_in`;
  `Booking.room` uses `PROTECT` so rooms with history can't be deleted (API returns 409).
- **`user_id`:** user management is out of scope, so it is a positive integer on the
  booking with no foreign key. Changing it to a FK or string is a one-line model change.
- **Timezones:** `USE_TZ=True`; datetimes should include an offset (naive values are
  interpreted as UTC).
- **No authentication/permissions** were added, as none were requested.
- **Not handled / next steps:** cancelling bookings, rejecting check-ins in the past,
  editing a room's features while it has future bookings (currently allowed),
  availability search endpoint, and the PostgreSQL exclusion constraint above.
