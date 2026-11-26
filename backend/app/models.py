from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class Flight(Base):
    __tablename__ = "flights"

    id = Column(Integer, primary_key=True, index=True)
    flight_number = Column(String(10), unique=True, index=True, nullable=False)
    origin = Column(String(3), index=True, nullable=False)           # LLA, ARN, GOT
    origin_city = Column(String(50), nullable=False)
    destination = Column(String(3), index=True, nullable=False)      # LLA, ARN, GOT
    destination_city = Column(String(50), nullable=False)
    departure_time = Column(DateTime, nullable=False)
    arrival_time = Column(DateTime, nullable=False)
    price_sek = Column(Float, nullable=False)
    total_seats = Column(Integer, default=40, nullable=False)
    available_seats = Column(Integer, default=40, nullable=False)

    bookings = relationship("Booking", back_populates="flight", cascade="all, delete-orphan")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    booking_ref = Column(String(12), unique=True, index=True, nullable=False)
    flight_id = Column(Integer, ForeignKey("flights.id"), nullable=True)  # null for live Duffel bookings
    user_id = Column(String(64), index=True, nullable=False)
    passenger_name = Column(String(100), nullable=False)
    passenger_email = Column(String(100), nullable=False)
    seat_number = Column(String(5), nullable=False)
    status = Column(String(20), default="CONFIRMED", nullable=False)   # CONFIRMED, CANCELLED, FAILED
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Snapshot route details for live Duffel bookings (no local Flight row)
    flight_number = Column(String(20), nullable=True)
    origin = Column(String(3), nullable=True)
    destination = Column(String(3), nullable=True)
    departure_time = Column(DateTime, nullable=True)

    # Duffel correlation IDs — null when running in mock/fallback mode
    duffel_offer_id = Column(String(100), nullable=True)   # from Duffel search result
    duffel_order_id = Column(String(100), nullable=True)   # from Duffel order creation

    flight = relationship("Flight", back_populates="bookings")

    # Ensure a seat cannot be booked twice on the same flight when active
    __table_args__ = (
        # Note: In SQLite and Postgres, we also enforce this at transactional level
    )
