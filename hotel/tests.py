from datetime import datetime, timedelta, timezone

from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from .models import Booking, Room


BASE = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=30)


def dt(day, hour=12):
    """ISO datetime `day` days after a base date 30 days from now (day 0 allowed)."""
    return (BASE.replace(hour=hour) + timedelta(days=day)).isoformat()


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def ahead(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


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

    def test_feature_edit_blocked_with_upcoming_booking(self):
        room = Room.objects.create(label="101", number_of_beds=2, view="sea")
        booking = Booking.objects.create(user_id=1, room=room, check_in=dt(1), check_out=dt(2))
        url = f"/api/rooms/{room.pk}/"
        self.assertEqual(self.client.patch(url, {"number_of_beds": 3}).status_code, 409)
        self.assertEqual(self.client.patch(url, {"view": "yard"}).status_code, 409)
        self.assertEqual(
            self.client.put(url, {"label": "101", "number_of_beds": 4, "view": "sea"}).status_code, 409
        )
        room.refresh_from_db()
        self.assertEqual((room.number_of_beds, room.view), (2, "sea"))
        # label change and unchanged features are fine
        self.assertEqual(self.client.patch(url, {"label": "101-A"}).status_code, 200)
        self.assertEqual(
            self.client.put(url, {"label": "101-A", "number_of_beds": 2, "view": "sea"}).status_code, 200
        )
        # after cancelling, features can change
        self.client.post(f"/api/bookings/{booking.pk}/cancel/")
        self.assertEqual(self.client.patch(url, {"number_of_beds": 3}).status_code, 200)

    def test_feature_edit_allowed_with_only_past_bookings(self):
        room = Room.objects.create(label="101", number_of_beds=2, view="sea")
        Booking.objects.create(user_id=1, room=room, check_in=ago(10), check_out=ago(8))
        self.assertEqual(self.client.patch(f"/api/rooms/{room.pk}/", {"view": "yard"}).status_code, 200)

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

    def test_past_check_in_rejected(self):
        r = self.book(ago(1), ahead(2))
        self.assertEqual(r.status_code, 400)
        self.assertIn("check_in", r.data)
        self.assertEqual(Booking.objects.count(), 0)

    # --- cancellation ---------------------------------------------------
    def test_cancel_frees_the_room(self):
        self.book(dt(1), dt(3))
        self.book(dt(1), dt(3), user_id=2)
        self.assertEqual(self.book(dt(1), dt(3), user_id=3).status_code, 409)
        r = self.client.post("/api/bookings/1/cancel/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "cancelled")
        self.assertIsNotNone(r.data["cancelled_at"])
        again = self.book(dt(1), dt(3), user_id=3)
        self.assertEqual(again.status_code, 201)
        self.assertEqual(again.data["room"]["label"], "101")

    def test_cancel_twice_conflicts(self):
        self.book(dt(1), dt(3))
        self.assertEqual(self.client.post("/api/bookings/1/cancel/").status_code, 200)
        self.assertEqual(self.client.post("/api/bookings/1/cancel/").status_code, 409)

    def test_cannot_cancel_started_booking(self):
        started = Booking.objects.create(
            user_id=1, room=self.r1,
            check_in=datetime.now(timezone.utc) - timedelta(hours=1),
            check_out=datetime.now(timezone.utc) + timedelta(days=1),
        )
        self.assertEqual(self.client.post(f"/api/bookings/{started.pk}/cancel/").status_code, 409)
        started.refresh_from_db()
        self.assertEqual(started.status, "confirmed")

    def test_cancel_unknown_404_and_status_filter(self):
        self.assertEqual(self.client.post("/api/bookings/999/cancel/").status_code, 404)
        self.book(dt(1), dt(2))
        self.book(dt(1), dt(2), user_id=2)
        self.client.post("/api/bookings/1/cancel/")
        self.assertEqual(self.client.get("/api/bookings/?status=cancelled").data["count"], 1)
        self.assertEqual(self.client.get("/api/bookings/?status=confirmed").data["count"], 1)

    # --- availability ---------------------------------------------------
    def available(self, **params):
        return self.client.get("/api/rooms/available/", params)

    def labels(self, response):
        return [r["label"] for r in response.data["results"]]

    def test_availability_filters_and_excludes_busy(self):
        self.assertEqual(self.labels(self.available(check_in=dt(1), check_out=dt(2))), ["101", "102", "201"])
        self.assertEqual(
            self.labels(self.available(check_in=dt(1), check_out=dt(2), number_of_beds=2, view="sea")),
            ["101", "102"],
        )
        self.assertEqual(self.labels(self.available(check_in=dt(1), check_out=dt(2), view="yard")), ["201"])
        self.book(dt(1), dt(4))  # takes 101
        self.assertEqual(
            self.labels(self.available(check_in=dt(2), check_out=dt(3), number_of_beds=2)), ["102"]
        )

    def test_availability_back_to_back_and_cancelled(self):
        self.book(dt(1), dt(3))
        self.assertIn("101", self.labels(self.available(check_in=dt(3), check_out=dt(5))))
        self.assertNotIn("101", self.labels(self.available(check_in=dt(2), check_out=dt(5))))
        self.client.post("/api/bookings/1/cancel/")
        self.assertIn("101", self.labels(self.available(check_in=dt(2), check_out=dt(5))))

    def test_availability_validation(self):
        self.assertEqual(self.available().status_code, 400)
        self.assertEqual(self.available(check_in=dt(3), check_out=dt(2)).status_code, 400)
        self.assertEqual(self.available(check_in=ago(1), check_out=dt(2)).status_code, 400)
        self.assertEqual(self.available(check_in=dt(1), check_out=dt(2), view="moon").status_code, 400)