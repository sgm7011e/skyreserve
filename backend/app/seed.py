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
    
    # Major Pan-European direct routes
    ("ARN", "Stockholm Arlanda", "LHR", "London Heathrow", 155, 1450.0),
    ("LHR", "London Heathrow", "ARN", "Stockholm Arlanda", 155, 1490.0),
    ("ARN", "Stockholm Arlanda", "CDG", "Paris Charles de Gaulle", 160, 1550.0),
    ("CDG", "Paris Charles de Gaulle", "ARN", "Stockholm Arlanda", 160, 1520.0),
    ("ARN", "Stockholm Arlanda", "BER", "Berlin Brandenburg", 100, 1150.0),
    ("BER", "Berlin Brandenburg", "ARN", "Stockholm Arlanda", 100, 1180.0),
    ("ARN", "Stockholm Arlanda", "AMS", "Amsterdam Schiphol", 125, 1290.0),
    ("AMS", "Amsterdam Schiphol", "ARN", "Stockholm Arlanda", 125, 1280.0),
    
    ("LHR", "London Heathrow", "CDG", "Paris Charles de Gaulle", 80, 950.0),
    ("CDG", "Paris Charles de Gaulle", "LHR", "London Heathrow", 80, 950.0),
    ("BER", "Berlin Brandenburg", "BCN", "Barcelona El Prat", 150, 1350.0),
    ("BCN", "Barcelona El Prat", "BER", "Berlin Brandenburg", 150, 1380.0),
    ("CDG", "Paris Charles de Gaulle", "FCO", "Rome Fiumicino", 125, 1220.0),
    ("FCO", "Rome Fiumicino", "CDG", "Paris Charles de Gaulle", 125, 1250.0),
    ("AMS", "Amsterdam Schiphol", "BCN", "Barcelona El Prat", 135, 1390.0),
    ("BCN", "Barcelona El Prat", "AMS", "Amsterdam Schiphol", 135, 1410.0),
]

FLIGHT_TIMES = [
    (7, 0, "SK101"),
    (9, 45, "SK103"),
    (13, 15, "SK105"),
    (17, 30, "SK107"),
    (20, 15, "SK109")
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
            for dep_hour, dep_min, base_code in FLIGHT_TIMES[:2]: # 2 flights per route per day
                flight_seq += 1
                dep_time = current_day.replace(hour=dep_hour, minute=dep_min)
                arr_time = dep_time + timedelta(minutes=duration_min)
                flight_num = f"{base_code[:2]}{flight_seq}"

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
            user_id="user-chew-002",
            passenger_name="Chew Yun",
            passenger_email="chewyun@group8.se",
            seat_number="1A",
            status="CONFIRMED"
        )
        demo_booking2 = Booking(
            booking_ref="BK-DEMO-02",
            flight_id=first_flight.id,
            user_id="user-xena-003",
            passenger_name="Xena Lim",
            passenger_email="xena@group8.se",
            seat_number="1B",
            status="CONFIRMED"
        )
        first_flight.available_seats -= 2
        db.add_all([demo_booking1, demo_booking2])
        db.commit()
