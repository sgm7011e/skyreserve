"""
duffel.py — Duffel API adapter with local mock fallback.

If DUFFEL_API_KEY is set in the environment, every flight search and booking
goes through the real Duffel sandbox API.  If the env var is absent (or empty),
the adapter falls back to the locally-seeded Flight rows so the app always
works without an external dependency.

Duffel REST flow:
  1. POST /air/offer_requests  → offer_request_id
  2. GET  /air/offers?offer_request_id=<id>  → list[offer]
  3. POST /air/orders          → order  (confirmed booking)
  4. GET  /air/orders/<id>     → retrieve existing order
  5. POST /air/orders/<id>/actions/void  → cancel / void

All amounts from Duffel are in minor currency units (pence/öre); we convert
to SEK by using the offer's total_amount and total_currency fields and doing
a simple pass-through (Duffel sandbox uses GBP; we show the value with the
currency label as returned).
"""

import os
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)

DUFFEL_BASE = "https://api.duffel.com"
DUFFEL_VERSION = "v2"


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Duffel-Version": DUFFEL_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _duffel_offer_to_flight_dict(offer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map a single Duffel offer object to the dict shape our FlightResponse
    schema expects, so the rest of the app doesn't care which adapter is active.

    Duffel gives amounts as strings like "120.50" in the offer currency.
    We store them as-is in price_sek (and also store the currency for the UI).
    """
    slices = offer.get("slices", [])
    if not slices:
        return {}

    seg = slices[0].get("segments", [{}])[0]
    dep_str = seg.get("departing_at", "")
    arr_str = seg.get("arriving_at", "")

    try:
        dep_dt = datetime.fromisoformat(dep_str)
    except (ValueError, TypeError):
        dep_dt = datetime.utcnow()

    try:
        arr_dt = datetime.fromisoformat(arr_str)
    except (ValueError, TypeError):
        arr_dt = dep_dt + timedelta(hours=2)

    origin_place = slices[0].get("origin", {})
    dest_place   = slices[0].get("destination", {})

    origin_iata  = origin_place.get("iata_code", "???")
    dest_iata    = dest_place.get("iata_code", "???")
    origin_city  = origin_place.get("city_name") or origin_place.get("name", origin_iata)
    dest_city    = dest_place.get("city_name") or dest_place.get("name", dest_iata)

    carrier = seg.get("operating_carrier", seg.get("marketing_carrier", {}))
    fn_number = seg.get("operating_carrier_flight_number") or seg.get("marketing_carrier_flight_number", "")
    flight_number = f"{carrier.get('iata_code','??')}{fn_number}"

    total_amount   = float(offer.get("total_amount", 0))
    total_currency = offer.get("total_currency", "GBP")
    fx_to_sek = {"SEK": 1.0, "GBP": 13.4, "EUR": 11.5, "USD": 10.8}.get(total_currency, 13.4)

    # Available seats: Duffel provides this per-slice, default to remaining count
    avail = offer.get("available_seats") or slices[0].get("fare_brand_name") or 40

    return {
        "id": offer["id"],           # Duffel offer ID used as the "flight id" in live mode
        "duffel_offer_id": offer["id"],
        "flight_number": flight_number,
        "origin": origin_iata,
        "origin_city": origin_city,
        "destination": dest_iata,
        "destination_city": dest_city,
        "departure_time": dep_dt,
        "arrival_time": arr_dt,
        "price_sek": round(total_amount * fx_to_sek, 2),
        "total_seats": 40,
        "available_seats": 40,
        # Extra fields carried for internal reference
        "_currency": total_currency,
        "_duffel_offer_id": offer["id"],
        "_passengers": offer.get("passengers", []),
    }


class DuffelAdapter:
    """
    Thin wrapper over the Duffel REST API with automatic mock fallback.

    Usage:
        adapter = DuffelAdapter()
        flights = adapter.search_flights("ARN", "LHR", "2026-12-01")
        order   = adapter.create_order(offer_id, passenger_info)
        adapter.cancel_order(order_id)
    """

    def __init__(self):
        self.token: Optional[str] = os.environ.get("DUFFEL_API_KEY", "").strip() or None
        if self.token:
            logger.info("DuffelAdapter: LIVE mode — calls go to Duffel sandbox API.")
        else:
            logger.info("DuffelAdapter: MOCK mode — using local seeded flight data.")

    @property
    def is_live(self) -> bool:
        return self.token is not None

    # ------------------------------------------------------------------
    # Flight search
    # ------------------------------------------------------------------

    def search_flights(
        self,
        origin: str,
        destination: str,
        date: str,
        passengers: int = 1,
        db=None,
    ) -> List[Dict[str, Any]]:
        """
        Return a list of flight dicts compatible with FlightResponse schema.

        In live mode: calls Duffel API (offer_request → offers).
        In mock mode: queries the local Flight table (db must be provided).
        """
        if self.is_live:
            return self._live_search(origin, destination, date, passengers)
        else:
            return self._mock_search(origin, destination, date, db)

    def _live_search(self, origin: str, destination: str, date: str, passengers: int) -> List[Dict[str, Any]]:
        if not origin.strip() or not destination.strip():
            return []

        departure_date = date.strip() or datetime.utcnow().strftime("%Y-%m-%d")

        body = {
            "data": {
                "slices": [
                    {
                        "origin": origin.strip().upper(),
                        "destination": destination.strip().upper(),
                        "departure_date": departure_date,
                    }
                ],
                "passengers": [{"type": "adult"} for _ in range(passengers)],
                "cabin_class": "economy",
            }
        }

        try:
            with httpx.Client(timeout=30) as client:
                # Step 1: create offer request
                r1 = client.post(
                    f"{DUFFEL_BASE}/air/offer_requests",
                    json=body,
                    headers=_headers(self.token),
                )
                r1.raise_for_status()
                offer_request_id = r1.json()["data"]["id"]

                # Step 2: fetch offers
                r2 = client.get(
                    f"{DUFFEL_BASE}/air/offers",
                    params={"offer_request_id": offer_request_id, "limit": 20},
                    headers=_headers(self.token),
                )
                r2.raise_for_status()
                offers = r2.json().get("data", [])

        except httpx.HTTPStatusError as exc:
            logger.error("Duffel API error during search: %s — %s", exc.response.status_code, exc.response.text)
            return []
        except Exception as exc:
            logger.error("Duffel search failed: %s", exc)
            return []

        results = []
        for offer in offers:
            mapped = _duffel_offer_to_flight_dict(offer)
            if mapped:
                results.append(mapped)
        return results

    def _mock_search(self, origin: str, destination: str, date: str, db) -> List[Dict[str, Any]]:
        """Query the locally-seeded Flight table and return compatible dicts."""
        if db is None:
            logger.warning("Mock search called without a db session — returning empty list.")
            return []

        from app.models import Flight
        from sqlalchemy import func as sqlfunc

        query = db.query(Flight)
        if origin:
            query = query.filter(Flight.origin == origin.upper().strip())
        if destination:
            query = query.filter(Flight.destination == destination.upper().strip())
        if date:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
                query = query.filter(sqlfunc.date(Flight.departure_time) == target_date)
            except ValueError:
                pass

        flights = query.order_by(Flight.departure_time.asc()).all()

        results = []
        for f in flights:
            results.append({
                "id": f.id,
                "flight_number": f.flight_number,
                "origin": f.origin,
                "origin_city": f.origin_city,
                "destination": f.destination,
                "destination_city": f.destination_city,
                "departure_time": f.departure_time,
                "arrival_time": f.arrival_time,
                "price_sek": f.price_sek,
                "total_seats": f.total_seats,
                "available_seats": f.available_seats,
                "_duffel_offer_id": None,
                "_currency": "SEK",
                "_passengers": [],
            })
        return results

    # ------------------------------------------------------------------
    # Offer lookup & Order creation (booking)
    # ------------------------------------------------------------------

    def get_offer(self, offer_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a raw Duffel offer by ID, or None if unavailable."""
        if not self.is_live or not offer_id:
            return None
        try:
            with httpx.Client(timeout=30) as client:
                r = client.get(
                    f"{DUFFEL_BASE}/air/offers/{offer_id}",
                    headers=_headers(self.token),
                )
                r.raise_for_status()
                return r.json().get("data")
        except Exception as exc:
            logger.error("Duffel get_offer failed for %s: %s", offer_id, exc)
            return None

    def create_order(
        self,
        offer_id: str,
        passenger_name: str,
        passenger_email: str,
        # Duffel needs DOB and phone for real orders; we use sensible defaults
        # for sandbox testing when real passenger details aren't collected yet
        born_on: str = "1990-01-01",
        phone_number: str = "+46700000000",
        title: str = "mr",
        gender: str = "m",
    ) -> Optional[str]:
        """
        Create a Duffel order for the given offer_id.
        Returns the Duffel order ID on success, or None if the call fails.

        In mock mode, always returns None (no external order needed).
        """
        if not self.is_live:
            return None

        # Split name into given / family (best-effort)
        parts = passenger_name.strip().split(maxsplit=1)
        given_name  = parts[0] if parts else "Passenger"
        family_name = parts[1] if len(parts) > 1 else "Guest"

        # First, fetch the offer to get passenger IDs and exact payment amount/currency
        try:
            with httpx.Client(timeout=30) as client:
                r_offer = client.get(
                    f"{DUFFEL_BASE}/air/offers/{offer_id}",
                    headers=_headers(self.token),
                )
                r_offer.raise_for_status()
                offer_data = r_offer.json()["data"]
                duffel_passengers = offer_data.get("passengers", [])

                # Build passenger list using the IDs Duffel already assigned
                passengers_body = []
                for p in duffel_passengers:
                    passengers_body.append({
                        "id": p["id"],
                        "given_name": given_name,
                        "family_name": family_name,
                        "email": passenger_email,
                        "born_on": born_on,
                        "title": title,
                        "gender": gender,
                        "phone_number": phone_number,
                    })

                body = {
                    "data": {
                        "type": "instant",
                        "selected_offers": [offer_id],
                        "passengers": passengers_body,
                        "payments": [
                            {
                                "type": "balance",
                                "amount": str(offer_data["total_amount"]),
                                "currency": offer_data["total_currency"],
                            }
                        ],
                    }
                }

                r_order = client.post(
                    f"{DUFFEL_BASE}/air/orders",
                    json=body,
                    headers=_headers(self.token),
                )
                r_order.raise_for_status()
                order_id = r_order.json()["data"]["id"]
                logger.info("Duffel order created: %s", order_id)
                return order_id

        except httpx.HTTPStatusError as exc:
            logger.error("Duffel order creation failed: %s — %s", exc.response.status_code, exc.response.text)
            return None
        except Exception as exc:
            logger.error("Duffel order creation failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Order cancellation (Saga compensation step)
    # ------------------------------------------------------------------

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a Duffel order via the two-step Order Cancellations API.
        Returns True on success; in mock mode always returns True.
        """
        if not self.is_live or not order_id:
            return True

        try:
            with httpx.Client(timeout=30) as client:
                r_quote = client.post(
                    f"{DUFFEL_BASE}/air/order_cancellations",
                    json={"data": {"order_id": order_id}},
                    headers=_headers(self.token),
                )
                r_quote.raise_for_status()
                cancellation_id = r_quote.json()["data"]["id"]

                r_confirm = client.post(
                    f"{DUFFEL_BASE}/air/order_cancellations/{cancellation_id}/actions/confirm",
                    headers=_headers(self.token),
                    content=b"{}",
                )
                r_confirm.raise_for_status()
                logger.info("Duffel order cancelled: %s (cancellation %s)", order_id, cancellation_id)
                return True
        except httpx.HTTPStatusError as exc:
            logger.error("Duffel cancellation failed: %s — %s", exc.response.status_code, exc.response.text)
            return False
        except Exception as exc:
            logger.error("Duffel cancellation failed: %s", exc)
            return False


# Module-level singleton — imported by main.py
adapter = DuffelAdapter()
