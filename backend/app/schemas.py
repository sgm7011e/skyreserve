from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

class FlightBase(BaseModel):
    flight_number: str
    origin: str
    origin_city: str
    destination: str
    destination_city: str
    departure_time: datetime
    arrival_time: datetime
    price_sek: float
    total_seats: int
    available_seats: int

class FlightResponse(FlightBase):
    id: int | str
    duffel_offer_id: Optional[str] = None

    class Config:
        from_attributes = True

class FlightDetailResponse(FlightResponse):
    booked_seats: List[str] = []
    all_seats: List[str] = []

class BookingCreateRequest(BaseModel):
    flight_id: int | str
    passenger_name: str
    passenger_email: str
    seat_number: str
    duffel_offer_id: Optional[str] = None   # supplied by frontend when in live Duffel mode
    flight_number: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    departure_time: Optional[datetime] = None

class BookingResponse(BaseModel):
    id: int
    booking_ref: str
    flight_id: Optional[int] = None
    flight_number: str
    origin: str
    destination: str
    departure_time: datetime
    passenger_name: str
    passenger_email: str
    seat_number: str
    status: str
    created_at: datetime
    duffel_offer_id: Optional[str] = None
    duffel_order_id: Optional[str] = None

    class Config:
        from_attributes = True

class UserProfile(BaseModel):
    user_id: str
    name: str
    email: str
    role: str

class MessageResponse(BaseModel):
    message: str
    status: str
