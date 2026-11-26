from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import Flight, Booking

SEAT_ROWS = [str(r) for r in range(1, 11)]
SEAT_COLS = ["A", "B", "C", "D"]
ALL_SEATS = [f"{r}{c}" for r in SEAT_ROWS for c in SEAT_COLS]  # 40 seats: 1A..10D

ROUTES = [
    # Swedish & Nordic connections
    ("LLA", "Luleå Kallax", "ARN", "Stockholm Arlanda", 75, 895.0),
    ("ARN", "Stockholm Arlanda", "LLA", "Luleå Kallax", 75, 920.0),
]

FLIGHT_TIMES = [
    (7, 0),
    (9, 45),
    (13, 15),
    (17, 30),
    (20, 15)
]

def seed_database(db: Session, force: bool = False):
    """Populates the database with initial regional flights if empty."""
    existing_count = db.query(Flight).count()
    if existing_count > 0 and not force:
        return

    if force:
        db.query(Booking).delete()
        db.query(Flight).delete()
        db.commit()

    base_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    flight_seq = 100

    for day_offset in range(0, 7):
        current_day = base_date + timedelta(days=day_offset)

        for origin, o_city, dest, d_city, duration_min, price in ROUTES:
            for dep_hour, dep_min in FLIGHT_TIMES:
                flight_seq += 1
                dep_time = current_day.replace(hour=dep_hour, minute=dep_min)
                arr_time = dep_time + timedelta(minutes=duration_min)
                flight_num = f"SK{flight_seq}"

                flight = Flight(
                    flight_number=flight_num,
                    origin=origin,
                    origin_city=o_city,
                    destination=dest,
                    destination_city=d_city,
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    price_sek=price,
                    total_seats=40,
                    available_seats=40
                )
                db.add(flight)  

    db.commit()

    # Pre-book a couple seats on flight 1 to demonstrate seat map occupancy
    first_flight = db.query(Flight).first()
    if first_flight:
        demo_booking1 = Booking(
            booking_ref="BK-DEMO-01",
            flight_id=first_flight.id,
            user_id="user-darren-001",
            passenger_name="Darren Chai",
            passenger_email="darren@gmail.com",
            seat_number="1A",
            status="CONFIRMED"
        )
        demo_booking2 = Booking(
            booking_ref="BK-DEMO-02",
            flight_id=first_flight.id,
            user_id="user-xena-002",
            passenger_name="Xena Lim",
            passenger_email="xena@gmail.com",
            seat_number="1B",
            status="CONFIRMED"
        )
        first_flight.available_seats -= 2
        db.add_all([demo_booking1, demo_booking2])
        db.commit()
