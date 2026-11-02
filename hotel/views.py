from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .exceptions import Conflict
from .models import Booking, Room
from .serializers import (
    AvailabilityQuerySerializer,
    BookingRequestSerializer,
    BookingSerializer,
    RescheduleRequestSerializer,
    RoomSerializer,
)
from .services import (
    BookingStateError,
    NoRoomAvailable,
    available_rooms,
    book_room,
    cancel_booking,
    reschedule_booking,
)


class RoomViewSet(viewsets.ModelViewSet):
    serializer_class = RoomSerializer

    def get_queryset(self):
        qs = Room.objects.all()
        if self.action in ("update", "partial_update"):
            # Lock the row so a concurrent booking cannot slip in between the
            # "has upcoming bookings?" check and the save.
            qs = qs.select_for_update()
        return qs

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        room = self.get_object()
        if room.bookings.exists():
            raise Conflict("Room has bookings and cannot be deleted.")
        room.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def available(self, request):
        """GET /api/rooms/available/?check_in=&check_out=[&number_of_beds=][&view=]"""
        query = AvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rooms = available_rooms(**query.validated_data)
        page = self.paginate_queryset(rooms)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)


class BookingViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = BookingSerializer

    def get_queryset(self):
        qs = Booking.objects.select_related("room", "rescheduled_to")
        params = self.request.query_params
        user_id = params.get("user_id")
        if user_id and user_id.isdigit():
            qs = qs.filter(user_id=int(user_id))
        if params.get("status") in Booking.Status.values:
            qs = qs.filter(status=params["status"])
        return qs

    def create(self, request, *args, **kwargs):
        req = BookingRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        try:
            booking = book_room(**req.validated_data)
        except NoRoomAvailable:
            raise Conflict("No room is available for the requested features and period.")
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()  # 404 if unknown
        try:
            booking = cancel_booking(booking.pk)
        except BookingStateError as exc:
            raise Conflict(str(exc))
        return Response(BookingSerializer(booking).data)

    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        """Replace this booking with a new one for new dates (old one is kept)."""
        booking = self.get_object()  # 404 if unknown
        req = RescheduleRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        try:
            new_booking = reschedule_booking(booking.pk, **req.validated_data)
        except BookingStateError as exc:
            raise Conflict(str(exc))
        except NoRoomAvailable:
            raise Conflict(
                "No room is available for the new period; "
                "the original booking is unchanged."
            )
        return Response(BookingSerializer(new_booking).data, status=status.HTTP_201_CREATED)