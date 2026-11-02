from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from .models import Booking, Room


class NoRoomAvailable(Exception):
    """No room matches the requested features for the requested period."""


class BookingNotCancellable(Exception):
    """The booking is already cancelled or has already started."""


def _blocking_bookings(check_in, check_out):
    """Confirmed bookings overlapping the half-open period [check_in, check_out).

    Two periods overlap iff existing.check_in < check_out AND
    existing.check_out > check_in, so back-to-back stays do not conflict.
    Cancelled bookings never block a room.
    """
    return Booking.objects.filter(
        status=Booking.Status.CONFIRMED,
        check_in__lt=check_out,
        check_out__gt=check_in,
    )


def available_rooms(*, check_in, check_out, number_of_beds=None, view=None):
    """Rooms (optionally filtered by features) free for the whole period."""
    rooms = Room.objects.all()
    if number_of_beds is not None:
        rooms = rooms.filter(number_of_beds=number_of_beds)
    if view is not None:
        rooms = rooms.filter(view=view)
    busy = _blocking_bookings(check_in, check_out).filter(room=OuterRef("pk"))
    return rooms.exclude(Exists(busy)).order_by("id")


def book_room(*, user_id, number_of_beds, view, check_in, check_out) -> Booking:
    """Assign the first free room matching the features and book it.

    Concurrency: all rooms matching the features are locked
    (SELECT ... FOR UPDATE, in a stable id order) for the duration of the
    transaction, so two requests competing for the same kind of room are
    serialized and cannot both pass the overlap check. SQLite ignores row
    locks but serializes writers anyway.
    """
    with transaction.atomic():
        rooms = list(
            Room.objects.select_for_update()
            .filter(number_of_beds=number_of_beds, view=view)
            .order_by("id")
        )
        if not rooms:
            raise NoRoomAvailable()

        busy_room_ids = set(
            _blocking_bookings(check_in, check_out)
            .filter(room__in=rooms)
            .values_list("room_id", flat=True)
        )
        for room in rooms:
            if room.id not in busy_room_ids:
                return Booking.objects.create(
                    user_id=user_id, room=room, check_in=check_in, check_out=check_out
                )
        raise NoRoomAvailable()


def cancel_booking(booking_id) -> Booking:
    """Cancel a confirmed booking that has not started yet."""
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking_id)
        if booking.status == Booking.Status.CANCELLED:
            raise BookingNotCancellable("Booking is already cancelled.")
        now = timezone.now()
        if booking.check_in <= now:
            raise BookingNotCancellable(
                "Booking has already started and cannot be cancelled."
            )
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = now
        booking.save(update_fields=["status", "cancelled_at"])
    return booking