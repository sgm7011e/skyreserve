import uuid
from typing import List, Optional
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.database import engine, Base, get_db
from app.models import Flight, Booking
from app.schemas import (
    FlightResponse,
    FlightDetailResponse,
    BookingCreateRequest,
    BookingResponse,
    UserProfile,
    MessageResponse
)
from app.auth import get_current_user
from app.seed import seed_database, ALL_SEATS
from app.duffel import adapter as duffel_adapter

# Create database tables automatically on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="SkyReserve API",
    description="Direct European Flight Booking Platform - M7011E Group 8",
    version="1.0.0"
)

# CORS: allow all origins for local dev; tightened at Traefik level in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ensure_booking_schema():
    """Idempotent Postgres schema migration for live Duffel booking columns."""
    if engine.name != "postgresql":
        return
    statements = [
        "ALTER TABLE bookings ALTER COLUMN flight_id DROP NOT NULL;",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS flight_number VARCHAR(20);",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS origin VARCHAR(3);",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS destination VARCHAR(3);",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS departure_time TIMESTAMP;",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS duffel_offer_id VARCHAR(100);",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS duffel_order_id VARCHAR(100);",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


@app.on_event("startup")
def startup_event():
    _ensure_booking_schema()
    db = next(get_db())
    seed_database(db)


@app.get("/health", tags=["System"])
def health_check():
    """Health probe used by Kubernetes liveness & readiness checks."""
    return {
        "status": "healthy",
        "service": "skyreserve-backend",
        "group": "Group 8",
        "cluster_domain": "group-8-m7011e-ltu.se",
        "duffel_mode": "live" if duffel_adapter.is_live else "mock",
    }


@app.get("/api/me", response_model=UserProfile, tags=["Auth"])
def get_me(current_user: UserProfile = Depends(get_current_user)):
    """Returns the current authenticated passenger profile."""
    return current_user


# ---------------------------------------------------------------------------
# Flight search — routes through Duffel adapter (live or mock)
# ---------------------------------------------------------------------------

@app.get("/api/flights", response_model=List[FlightResponse], tags=["Flights"])
def search_flights(
    origin: Optional[str] = Query(None, description="Origin IATA code, e.g. LLA"),
    destination: Optional[str] = Query(None, description="Destination IATA code, e.g. ARN"),
    date: Optional[str] = Query(None, description="Flight date in YYYY-MM-DD format"),
    db: Session = Depends(get_db)
):
    """
    Search available direct flights by route and date.

    In LIVE mode (DUFFEL_API_KEY set): queries Duffel sandbox for real offers.
    In MOCK mode (no token): queries locally-seeded Flight rows.

    Both modes return the same response schema so the frontend never needs to care.
    """
    # Validate date format early so the user gets a 400, not a Duffel 422
    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    results = duffel_adapter.search_flights(
        origin=origin or "",
        destination=destination or "",
        date=date or "",
        db=db,
    )
    return results


@app.get("/api/flights/{flight_id}", response_model=FlightDetailResponse, tags=["Flights"])
def get_flight_details(flight_id: str, db: Session = Depends(get_db)):
    """
    Fetch flight details + occupied seat map for visual seat selection.

    In mock mode: flight_id is an integer PK from the Flight table.
    In live mode: flight_id is a Duffel offer ID string — booked seats are
    checked against local Booking rows sharing the same duffel_offer_id.
    """
    if flight_id.startswith("off_") or (duffel_adapter.is_live and not flight_id.isdigit()):
        booked_seats = [
            b.seat_number
            for b in db.query(Booking).filter(
                Booking.duffel_offer_id == flight_id,
                Booking.status == "CONFIRMED",
            ).all()
        ]
        return FlightDetailResponse(
            id=flight_id,
            duffel_offer_id=flight_id,
            flight_number="",
            origin="",
            origin_city="",
            destination="",
            destination_city="",
            departure_time=datetime.utcnow(),
            arrival_time=datetime.utcnow(),
            price_sek=0.0,
            total_seats=40,
            available_seats=max(0, 40 - len(booked_seats)),
            booked_seats=booked_seats,
            all_seats=ALL_SEATS,
        )

    # Mock mode: look up local Flight row
    try:
        fid = int(flight_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid flight ID")

    flight = db.query(Flight).filter(Flight.id == fid).first()
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")

    booked_seats = [
        b.seat_number for b in flight.bookings
        if b.status == "CONFIRMED"
    ]

    return FlightDetailResponse(
        id=flight.id,
        flight_number=flight.flight_number,
        origin=flight.origin,
        origin_city=flight.origin_city,
        destination=flight.destination,
        destination_city=flight.destination_city,
        departure_time=flight.departure_time,
        arrival_time=flight.arrival_time,
        price_sek=flight.price_sek,
        total_seats=flight.total_seats,
        available_seats=flight.available_seats,
        booked_seats=booked_seats,
        all_seats=ALL_SEATS
    )


# ---------------------------------------------------------------------------
# Booking creation — ACID local record + optional Duffel order (Saga pattern)
# ---------------------------------------------------------------------------

@app.post("/api/bookings", response_model=BookingResponse, status_code=status.HTTP_201_CREATED, tags=["Bookings"])
def create_booking(
    payload: BookingCreateRequest,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ACID Atomic Seat Reservation with Saga compensation:

    1. Validate seat and check availability (local Flight row lock in mock mode,
       or duffel_offer_id seat check in live Duffel mode).
    2. Create a local Booking record with status=CONFIRMED.
    3. If Duffel live mode: call Duffel to create an order.
       - Success: store duffel_order_id in the booking record.
       - Failure: mark the booking FAILED (Saga compensation) and raise 502.
    4. Commit and return.
    """
    seat = payload.seat_number.upper().strip()
    if seat not in ALL_SEATS:
        raise HTTPException(status_code=400, detail=f"Invalid seat number: {seat}")

    raw_flight_id = str(payload.flight_id).strip()
    is_duffel_offer = bool(payload.duffel_offer_id) or not raw_flight_id.isdigit()

    local_flight_id: Optional[int] = None
    offer_id: Optional[str] = None
    flight: Optional[Flight] = None

    if is_duffel_offer:
        offer_id = (payload.duffel_offer_id or raw_flight_id).strip()
        existing_seat_booking = db.query(Booking).filter(
            Booking.duffel_offer_id == offer_id,
            Booking.seat_number == seat,
            Booking.status == "CONFIRMED"
        ).first()
        if existing_seat_booking:
            raise HTTPException(
                status_code=409,
                detail=f"Seat {seat} has already been reserved by another passenger."
            )
    else:
        local_flight_id = int(raw_flight_id)
        flight_query = db.query(Flight).filter(Flight.id == local_flight_id)
        if engine.name == "postgresql":
            flight = flight_query.with_for_update().first()
        else:
            flight = flight_query.first()

        if not flight:
            raise HTTPException(status_code=404, detail="Flight not found")

        if flight.available_seats <= 0:
            raise HTTPException(status_code=409, detail="Flight is fully booked")

        existing_seat_booking = db.query(Booking).filter(
            Booking.flight_id == flight.id,
            Booking.seat_number == seat,
            Booking.status == "CONFIRMED"
        ).first()

        if existing_seat_booking:
            raise HTTPException(
                status_code=409,
                detail=f"Seat {seat} has already been reserved by another passenger."
            )

    # Generate unique booking reference
    booking_ref = f"BK-{uuid.uuid4().hex[:6].upper()}"

    if flight:
        resp_flight_number = flight.flight_number
        resp_origin = flight.origin
        resp_destination = flight.destination
        resp_departure = flight.departure_time
    else:
        resp_flight_number = (payload.flight_number or booking_ref)[:20]
        resp_origin = (payload.origin or "")[:3].upper()
        resp_destination = (payload.destination or "")[:3].upper()
        dep_val = payload.departure_time or datetime.utcnow()
        resp_departure = dep_val.replace(tzinfo=None) if dep_val.tzinfo else dep_val

    booking = Booking(
        booking_ref=booking_ref,
        flight_id=local_flight_id,
        user_id=current_user.user_id,
        passenger_name=payload.passenger_name,
        passenger_email=str(payload.passenger_email),
        seat_number=seat,
        status="CONFIRMED",
        flight_number=resp_flight_number,
        origin=resp_origin,
        destination=resp_destination,
        departure_time=resp_departure,
        duffel_offer_id=offer_id,
        duffel_order_id=None,
    )

    if flight:
        flight.available_seats -= 1

    db.add(booking)
    db.commit()
    db.refresh(booking)

    # --- Saga step: attempt Duffel order creation ---
    if duffel_adapter.is_live and offer_id:
        order_id = duffel_adapter.create_order(
            offer_id=offer_id,
            passenger_name=payload.passenger_name,
            passenger_email=str(payload.passenger_email),
        )
        if order_id:
            booking.duffel_order_id = order_id
            db.commit()
            db.refresh(booking)
        else:
            # Saga compensation: Duffel order failed → mark local booking FAILED
            booking.status = "FAILED"
            if flight:
                flight.available_seats += 1
            db.commit()
            raise HTTPException(
                status_code=502,
                detail="Flight reservation could not be confirmed with the airline. Please try again."
            )

    return BookingResponse(
        id=booking.id,
        booking_ref=booking.booking_ref,
        flight_id=booking.flight_id,
        flight_number=resp_flight_number,
        origin=resp_origin,
        destination=resp_destination,
        departure_time=resp_departure,
        passenger_name=booking.passenger_name,
        passenger_email=booking.passenger_email,
        seat_number=booking.seat_number,
        status=booking.status,
        created_at=booking.created_at,
        duffel_offer_id=booking.duffel_offer_id,
        duffel_order_id=booking.duffel_order_id,
    )


@app.get("/api/bookings/my", response_model=List[BookingResponse], tags=["Bookings"])
def get_my_bookings(
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve all flight bookings for the current passenger."""
    bookings = db.query(Booking).filter(
        Booking.user_id == current_user.user_id
    ).order_by(Booking.created_at.desc()).all()

    results = []
    for b in bookings:
        if b.flight is not None:
            fn = b.flight.flight_number
            orig = b.flight.origin
            dest = b.flight.destination
            dep = b.flight.departure_time
        else:
            fn = b.flight_number or b.booking_ref
            orig = b.origin or ""
            dest = b.destination or ""
            dep = b.departure_time or b.created_at

        results.append(BookingResponse(
            id=b.id,
            booking_ref=b.booking_ref,
            flight_id=b.flight_id,
            flight_number=fn,
            origin=orig,
            destination=dest,
            departure_time=dep,
            passenger_name=b.passenger_name,
            passenger_email=b.passenger_email,
            seat_number=b.seat_number,
            status=b.status,
            created_at=b.created_at,
            duffel_offer_id=b.duffel_offer_id,
            duffel_order_id=b.duffel_order_id,
        ))
    return results


@app.delete("/api/bookings/{booking_id}", response_model=MessageResponse, tags=["Bookings"])
def cancel_booking(
    booking_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cancel a booking and restore the seat to available inventory.

    If a Duffel order ID is stored, the cancellation is forwarded to Duffel
    (Saga compensation) before the local record is updated.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.status == "CANCELLED":
        return MessageResponse(message="Booking is already cancelled", status="CANCELLED")

    # Saga compensation: cancel at Duffel if we have an order ID
    if booking.duffel_order_id:
        ok = duffel_adapter.cancel_order(booking.duffel_order_id)
        if not ok:
            # Log but don't block the local cancellation — idempotency is fine
            import logging
            logging.getLogger(__name__).warning(
                "Duffel cancellation failed for order %s — local record still cancelled.",
                booking.duffel_order_id
            )

    booking.status = "CANCELLED"
    if booking.flight is not None:
        booking.flight.available_seats += 1
    db.commit()

    return MessageResponse(message="Booking cancelled successfully. Seat restored.", status="CANCELLED")


@app.post("/api/admin/reset", response_model=MessageResponse, tags=["Admin"])
def reset_database(db: Session = Depends(get_db)):
    """Reset database and re-seed flight schedules (convenient for demos)."""
    seed_database(db, force=True)
    return MessageResponse(message="Database re-seeded successfully with fresh schedules", status="SUCCESS")
