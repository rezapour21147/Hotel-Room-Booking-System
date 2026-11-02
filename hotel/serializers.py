from django.utils import timezone
from rest_framework import serializers

from .exceptions import Conflict
from .models import Booking, Room
from django.core.exceptions import ObjectDoesNotExist

class RoomSerializer(serializers.ModelSerializer):
    view = serializers.ChoiceField(choices=Room.View.choices)

    class Meta:
        model = Room
        fields = ["id", "label", "number_of_beds", "view"]

    def validate(self, attrs):
        # Changing beds/view would silently invalidate bookings that were made
        # for the old features, so it is refused while any upcoming or ongoing
        # confirmed booking exists. Renaming the label is always fine.
        if self.instance is not None:
            changes_features = any(
                field in attrs and attrs[field] != getattr(self.instance, field)
                for field in ("number_of_beds", "view")
            )
            if changes_features and self.instance.bookings.filter(
                status=Booking.Status.CONFIRMED, check_out__gt=timezone.now()
            ).exists():
                raise Conflict(
                    "Number of beds and view cannot be changed while the room has "
                    "upcoming or ongoing bookings. Cancel them first."
                )
        return attrs


class PeriodSerializer(serializers.Serializer):
    check_in = serializers.DateTimeField()
    check_out = serializers.DateTimeField()

    def validate(self, attrs):
        if attrs["check_in"] < timezone.now():
            raise serializers.ValidationError(
                {"check_in": "check_in cannot be in the past."}
            )
        if attrs["check_out"] <= attrs["check_in"]:
            raise serializers.ValidationError(
                {"check_out": "check_out must be after check_in."}
            )
        return attrs


class BookingRequestSerializer(PeriodSerializer):
    user_id = serializers.IntegerField(min_value=1)
    number_of_beds = serializers.IntegerField(min_value=1, max_value=5)
    view = serializers.ChoiceField(choices=Room.View.choices)


class AvailabilityQuerySerializer(PeriodSerializer):
    number_of_beds = serializers.IntegerField(min_value=1, max_value=5, required=False)
    view = serializers.ChoiceField(choices=Room.View.choices, required=False)

class RescheduleRequestSerializer(PeriodSerializer):
    """New dates for an existing booking; same rules as any other period."""


class BookingSerializer(serializers.ModelSerializer):
    room = RoomSerializer(read_only=True)
    rescheduled_to = serializers.SerializerMethodField()   

    def get_rescheduled_to(self, obj):                    
        try:
            return obj.rescheduled_to.pk
        except ObjectDoesNotExist:
            return None

    class Meta:
        model = Booking
        fields = [
            "id", "user_id", "room", "check_in", "check_out",
            "status", "cancelled_at", "rescheduled_from", "rescheduled_to",
            "created_at",
        ]