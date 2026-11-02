from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from .models import Booking, Room
from .serializers import BookingRequestSerializer, BookingSerializer, RoomSerializer
from .services import NoRoomAvailable, book_room


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Conflict."
    default_code = "conflict"


class RoomViewSet(viewsets.ModelViewSet):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer

    def destroy(self, request, *args, **kwargs):
        room = self.get_object()
        if room.bookings.exists():
            raise Conflict("Room has bookings and cannot be deleted.")
        room.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BookingViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = BookingSerializer

    def get_queryset(self):
        qs = Booking.objects.select_related("room")
        user_id = self.request.query_params.get("user_id")
        if user_id and user_id.isdigit():
            qs = qs.filter(user_id=int(user_id))
        return qs

    def create(self, request, *args, **kwargs):
        req = BookingRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        try:
            booking = book_room(**req.validated_data)
        except NoRoomAvailable:
            raise Conflict("No room is available for the requested features and period.")
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)
