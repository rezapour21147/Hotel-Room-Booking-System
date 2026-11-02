from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q


class Room(models.Model):
    class View(models.TextChoices):
        SEA = "sea", "Sea"
        MOUNTAIN = "mountain", "Mountain"
        YARD = "yard", "Yard"

    label = models.CharField(max_length=50, unique=True)
    number_of_beds = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    view = models.CharField(max_length=10, choices=View.choices)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(number_of_beds__gte=1, number_of_beds__lte=5),
                name="room_beds_between_1_and_5",
            )
        ]
        indexes = [models.Index(fields=["number_of_beds", "view"])]

    def __str__(self):
        return self.label


class Booking(models.Model):
    # User management is out of scope, so the user is just an opaque identifier.
    user_id = models.PositiveIntegerField(db_index=True)
    # PROTECT: a room with booking history must not be silently deleted.
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="bookings")
    check_in = models.DateTimeField()
    check_out = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(check_out__gt=F("check_in")),
                name="booking_check_out_after_check_in",
            )
        ]
        indexes = [models.Index(fields=["room", "check_in", "check_out"])]

    def __str__(self):
        return f"Booking {self.pk}: room {self.room_id} {self.check_in} -> {self.check_out}"
