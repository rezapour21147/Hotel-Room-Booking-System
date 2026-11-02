from django.db import transaction

from .models import Booking, Room


class NoRoomAvailable(Exception):
    """No room matches the requested features for the requested period."""


def book_room(*, user_id, number_of_beds, view, check_in, check_out) -> Booking:
    """Assign the first free room matching the features and book it.

    Intervals are half-open [check_in, check_out): a guest may check in at the
    exact moment the previous guest checks out.

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
            Booking.objects.filter(
                room__in=rooms,
                check_in__lt=check_out,
                check_out__gt=check_in,
            ).values_list("room_id", flat=True)
        )
        for room in rooms:
            if room.id not in busy_room_ids:
                return Booking.objects.create(
                    user_id=user_id, room=room, check_in=check_in, check_out=check_out
                )
        raise NoRoomAvailable()
