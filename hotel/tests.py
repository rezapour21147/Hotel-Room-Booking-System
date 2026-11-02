from datetime import datetime, timedelta, timezone

from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from .models import Booking, Room


def dt(day, hour=12):
    """ISO datetime `day` days after 2026-12-01 (day 0 is allowed)."""
    base = datetime(2026, 12, 1, hour, tzinfo=timezone.utc)
    return (base + timedelta(days=day)).isoformat()


class RoomApiTests(APITestCase):
    def test_crud(self):
        r = self.client.post("/api/rooms/", {"label": "101", "number_of_beds": 2, "view": "sea"})
        self.assertEqual(r.status_code, 201)
        pk = r.data["id"]
        self.assertEqual(self.client.get(f"/api/rooms/{pk}/").data["label"], "101")
        r = self.client.patch(f"/api/rooms/{pk}/", {"view": "yard"})
        self.assertEqual(r.data["view"], "yard")
        self.assertEqual(self.client.get("/api/rooms/").data["count"], 1)
        self.assertEqual(self.client.delete(f"/api/rooms/{pk}/").status_code, 204)

    def test_validation(self):
        Room.objects.create(label="101", number_of_beds=1, view="sea")
        bad = [
            {"label": "101", "number_of_beds": 1, "view": "sea"},  # duplicate
            {"label": "102", "number_of_beds": 0, "view": "sea"},
            {"label": "103", "number_of_beds": 6, "view": "sea"},
            {"label": "104", "number_of_beds": 2, "view": "garden"},
        ]
        for payload in bad:
            self.assertEqual(self.client.post("/api/rooms/", payload).status_code, 400, payload)

    def test_cannot_delete_room_with_bookings(self):
        room = Room.objects.create(label="101", number_of_beds=2, view="sea")
        Booking.objects.create(user_id=1, room=room, check_in=dt(1), check_out=dt(2))
        self.assertEqual(self.client.delete(f"/api/rooms/{room.pk}/").status_code, 409)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())


class BookingApiTests(APITestCase):
    def setUp(self):
        self.r1 = Room.objects.create(label="101", number_of_beds=2, view="sea")
        self.r2 = Room.objects.create(label="102", number_of_beds=2, view="sea")
        self.other = Room.objects.create(label="201", number_of_beds=3, view="yard")

    def book(self, check_in, check_out, user_id=1, beds=2, view="sea"):
        return self.client.post("/api/bookings/", {
            "user_id": user_id, "number_of_beds": beds, "view": view,
            "check_in": check_in, "check_out": check_out,
        })

    def test_books_matching_room(self):
        r = self.book(dt(1), dt(3))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["room"]["label"], "101")
        self.assertEqual(r.data["user_id"], 1)

    def test_overlap_goes_to_next_room_then_conflicts(self):
        self.assertEqual(self.book(dt(1), dt(5)).data["room"]["label"], "101")
        self.assertEqual(self.book(dt(3), dt(6), user_id=2).data["room"]["label"], "102")
        r = self.book(dt(4), dt(7), user_id=3)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Booking.objects.count(), 2)

    def test_overlap_variants(self):
        self.book(dt(10), dt(20))
        self.book(dt(10), dt(20), user_id=2)  # both rooms now busy
        cases = [(dt(8), dt(11)), (dt(19), dt(25)), (dt(12), dt(14)), (dt(5), dt(30))]
        for ci, co in cases:
            self.assertEqual(self.book(ci, co, user_id=9).status_code, 409, (ci, co))

    def test_back_to_back_is_allowed(self):
        self.book(dt(1), dt(3))
        self.book(dt(1), dt(3), user_id=2)
        self.assertEqual(self.book(dt(3), dt(5), user_id=3).data["room"]["label"], "101")
        self.assertEqual(self.book(dt(0), dt(1), user_id=4).status_code, 201)

    def test_no_matching_features(self):
        self.assertEqual(self.book(dt(1), dt(2), beds=2, view="mountain").status_code, 409)
        self.assertEqual(self.book(dt(1), dt(2), beds=4, view="sea").status_code, 409)

    def test_validation(self):
        self.assertEqual(self.book(dt(3), dt(3)).status_code, 400)
        self.assertEqual(self.book(dt(4), dt(3)).status_code, 400)
        self.assertEqual(self.book("nope", dt(3)).status_code, 400)
        self.assertEqual(self.book(dt(1), dt(2), beds=9).status_code, 400)
        self.assertEqual(self.book(dt(1), dt(2), view="moon").status_code, 400)
        self.assertEqual(self.client.post("/api/bookings/", {}).status_code, 400)

    def test_list_filter_and_retrieve(self):
        b = self.book(dt(1), dt(2), user_id=7).data
        self.book(dt(1), dt(2), user_id=8)
        self.assertEqual(self.client.get("/api/bookings/?user_id=7").data["count"], 1)
        self.assertEqual(self.client.get(f"/api/bookings/{b['id']}/").status_code, 200)

    def test_db_rejects_inverted_period(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.create(user_id=1, room=self.r1, check_in=dt(3), check_out=dt(2))
