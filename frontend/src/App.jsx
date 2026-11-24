import React, { useState, useEffect } from 'react';

// Known airports shown as datalist suggestions; user can also type any IATA code
const AIRPORTS = [
  { code: 'ARN', label: 'ARN - Stockholm Arlanda' },
  { code: 'LHR', label: 'LHR - London Heathrow' },
  { code: 'CDG', label: 'CDG - Paris Charles de Gaulle' },
  { code: 'BER', label: 'BER - Berlin Brandenburg' },
  { code: 'AMS', label: 'AMS - Amsterdam Schiphol' },
  { code: 'BCN', label: 'BCN - Barcelona El Prat' },
  { code: 'FCO', label: 'FCO - Rome Fiumicino' },
  { code: 'LLA', label: 'LLA - Luleå Kallax' },
];

export default function App() {
  const [flights, setFlights] = useState([]);
  const [searchOrigin, setSearchOrigin] = useState('');
  const [searchDest, setSearchDest] = useState('');
  const [searchDate, setSearchDate] = useState(new Date().toISOString().split('T')[0]);
  const [loading, setLoading] = useState(false);

  const [selectedFlight, setSelectedFlight] = useState(null);
  const [flightDetails, setFlightDetails] = useState(null);
  const [selectedSeat, setSelectedSeat] = useState('');
  const [passengerName, setPassengerName] = useState('Darren Chai');
  const [passengerEmail, setPassengerEmail] = useState('example@email.com');

  const [myBookings, setMyBookings] = useState([]);
  const [showMyBookings, setShowMyBookings] = useState(false);
  const [currentUser, setCurrentUser] = useState({ name: 'Darren Chai', role: 'passenger' });
  const [toast, setToast] = useState(null);

  const showToast = (message, type = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4500);
  };

  // Fetch flights
  const loadFlights = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (searchOrigin) params.append('origin', searchOrigin.toUpperCase().trim());
      if (searchDest) params.append('destination', searchDest.toUpperCase().trim());
      if (searchDate) params.append('date', searchDate);

      const res = await fetch(`/api/flights?${params.toString()}`);
      if (!res.ok) throw new Error('Failed to fetch flights');
      const data = await res.json();
      setFlights(data);
    } catch (err) {
      showToast('Error loading flights: ' + err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  // Fetch bookings for current user
  const loadMyBookings = async () => {
    try {
      const res = await fetch('/api/bookings/my');
      if (res.ok) {
        const data = await res.json();
        setMyBookings(data);
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    loadFlights();
    loadMyBookings();
    // Fetch profile
    fetch('/api/me')
      .then(res => res.json())
      .then(user => {
        if (user && user.name) {
          setCurrentUser(user);
          setPassengerName(user.name);
          setPassengerEmail(user.email);
        }
      })
      .catch(() => {});
  }, []);

  // Open seat selection modal
  const handleOpenSeatModal = async (flight) => {
    setSelectedFlight(flight);
    setSelectedSeat('');
    try {
      const res = await fetch(`/api/flights/${flight.id}`);
      if (!res.ok) throw new Error('Could not fetch flight details');
      const details = await res.json();
      setFlightDetails(details);
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  // Submit booking — passes duffel_offer_id when flight came from Duffel live mode
  const handleConfirmBooking = async (e) => {
    e.preventDefault();
    if (!selectedSeat) {
      showToast('Please select a seat on the cabin map first.', 'error');
      return;
    }

    try {
      const body = {
        flight_id: selectedFlight.id,
        passenger_name: passengerName,
        passenger_email: passengerEmail,
        seat_number: selectedSeat,
        // duffel_offer_id is set when in live Duffel mode (the flight id IS the offer id);
        // null/undefined in mock mode — backend handles both.
        duffel_offer_id: selectedFlight._duffel_offer_id || null,
      };

      const res = await fetch('/api/bookings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const data = await res.json();

      if (res.status === 409) {
        // Concurrency conflict / double-booking caught!
        showToast(`⚠️ Concurrency Conflict: ${data.detail}`, 'error');
        // Refresh seat map to show updated occupied seats
        handleOpenSeatModal(selectedFlight);
        return;
      }

      if (!res.ok) {
        throw new Error(data.detail || 'Booking failed');
      }

      showToast(`🎉 Confirmed! Ref: ${data.booking_ref} (Seat ${data.seat_number})`, 'success');
      setSelectedFlight(null);
      loadFlights();
      loadMyBookings();
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  // Cancel booking
  const handleCancelBooking = async (bookingId) => {
    if (!confirm('Are you sure you want to cancel this reservation? Seat will be released.')) return;
    try {
      const res = await fetch(`/api/bookings/${bookingId}`, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Cancellation failed');
      showToast('Booking cancelled. Seat inventory restored.', 'success');
      loadMyBookings();
      loadFlights();
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  // Admin reset
  const handleResetDemo = async () => {
    try {
      const res = await fetch('/api/admin/reset', { method: 'POST' });
      if (res.ok) {
        showToast('Demo reset: Schedules restored to fresh state.', 'success');
        loadFlights();
        loadMyBookings();
      }
    } catch (err) {
      showToast('Reset failed', 'error');
    }
  };

  // Format times
  const formatTime = (isoString) => {
    const d = new Date(isoString);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  // Currency label: use _currency if present (Duffel live), else SEK
  const priceLabel = (flight) => {
    const currency = flight._currency || 'SEK';
    return `${flight.price_sek} ${currency}`;
  };

  return (
    <div>
      {/* Top Navigation */}
      <header className="navbar">
        <div className="brand">
          <span className="brand-logo">✈️</span>
          <div>
            <div className="brand-title">SkyReserve</div>
            <div className="brand-subtitle">Direct European Flight Portal</div>
          </div>
        </div>

        <div className="nav-actions">
          <div className="user-badge">
            <span>👤</span>
            <span>{currentUser.name}</span>
            <span className="role-pill">{currentUser.role}</span>
          </div>

          <button className="nav-btn" onClick={() => setShowMyBookings(true)}>
            <span>📋 My Bookings ({myBookings.filter(b => b.status === 'CONFIRMED').length})</span>
          </button>

          <button
            style={{ background: 'transparent', border: '1px solid #475569', color: '#94a3b8', padding: '0.4rem 0.75rem', borderRadius: 6, fontSize: '0.75rem', cursor: 'pointer' }}
            onClick={handleResetDemo}
            title="Reset flight schedules for live demo testing"
          >
            Reset Demo
          </button>
        </div>
      </header>

      {/* Hero Banner */}
      <section className="hero-banner">
        <h1>Direct European Flight Booking</h1>
        <p>Book your direct flights easily and efficiently.</p>
      </section>

      {/* Search Filter Card */}
      {/* Hidden datalists power autocomplete suggestions on the IATA text inputs */}
      <datalist id="airport-list">
        {AIRPORTS.map(a => <option key={a.code} value={a.code}>{a.label}</option>)}
      </datalist>

      <div className="search-box-container">
        <div className="search-card">
          <div className="input-group">
            <label>Origin <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>(IATA code)</span></label>
            <input
              type="text"
              list="airport-list"
              placeholder="e.g. ARN"
              maxLength={3}
              value={searchOrigin}
              onChange={e => setSearchOrigin(e.target.value.toUpperCase())}
              style={{ textTransform: 'uppercase' }}
            />
          </div>

          <div className="input-group">
            <label>Destination <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>(IATA code)</span></label>
            <input
              type="text"
              list="airport-list"
              placeholder="e.g. LHR"
              maxLength={3}
              value={searchDest}
              onChange={e => setSearchDest(e.target.value.toUpperCase())}
              style={{ textTransform: 'uppercase' }}
            />
          </div>

          <div className="input-group">
            <label>Date</label>
            <input
              type="date"
              value={searchDate}
              onChange={e => setSearchDate(e.target.value)}
            />
          </div>

          <button className="btn-primary" onClick={loadFlights}>
            Search Flights
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <main className="main-container">
        <div className="results-header">
          <h2>Available Direct Flights ({flights.length})</h2>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Group 8 K3s Cluster • Domain: group-8-m7011e-ltu.se
          </span>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: '3rem', color: '#64748b' }}>Loading schedules...</div>
        ) : flights.length === 0 ? (
          <div style={{ background: 'white', padding: '3rem', textAlign: 'center', borderRadius: 12, border: '1px solid #e2e8f0' }}>
            <p style={{ fontSize: '1.1rem', fontWeight: 600, color: '#334155' }}>No flights found matching your route and date.</p>
            <p style={{ fontSize: '0.9rem', color: '#64748b', marginTop: '0.5rem' }}>Try clearing the filters or click "Reset Demo" above to restore sample flights.</p>
          </div>
        ) : (
          flights.map(flight => (
            <div key={flight.id} className="flight-card">
              <div className="flight-main">
                <span className="flight-num-badge">{flight.flight_number}</span>

                <div className="route-display">
                  <div className="route-stop">
                    <div className="time">{formatTime(flight.departure_time)}</div>
                    <div className="iata">{flight.origin}</div>
                    <div className="city">{flight.origin_city}</div>
                  </div>

                  <div className="flight-line">
                    <span className="flight-duration">Direct</span>
                    <div className="line-art"></div>
                  </div>

                  <div className="route-stop">
                    <div className="time">{formatTime(flight.arrival_time)}</div>
                    <div className="iata">{flight.destination}</div>
                    <div className="city">{flight.destination_city}</div>
                  </div>
                </div>
              </div>

              <div className="flight-pricing">
                <div className="price">{priceLabel(flight)}</div>
                <span className={`seat-avail ${flight.available_seats > 5 ? 'plenty' : 'limited'}`}>
                  {flight.available_seats > 0 ? `${flight.available_seats} seats left` : 'Sold Out'}
                </span>
                <button
                  className="btn-primary"
                  style={{ height: '38px', padding: '0 1.25rem', marginTop: '0.25rem' }}
                  disabled={flight.available_seats === 0}
                  onClick={() => handleOpenSeatModal(flight)}
                >
                  {flight.available_seats > 0 ? 'Select Seat' : 'Full'}
                </button>
              </div>
            </div>
          ))
        )}
      </main>

      {/* Seat Selection & Booking Modal */}
      {selectedFlight && (
        <div className="modal-backdrop">
          <div className="modal-content">
            <div className="modal-header">
              <div>
                <h3 style={{ fontSize: '1.25rem', fontWeight: 700 }}>
                  Select Seat • {selectedFlight.flight_number}
                </h3>
                <p style={{ fontSize: '0.85rem', color: '#64748b' }}>
                  {selectedFlight.origin} ({selectedFlight.origin_city}) → {selectedFlight.destination} ({selectedFlight.destination_city})
                </p>
              </div>
              <button className="close-btn" onClick={() => setSelectedFlight(null)}>✕</button>
            </div>

            <div className="seat-map-wrapper">
              <div className="plane-nose">Cockpit</div>
              <div className="seat-grid">
                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(row => (
                  <div key={`row-${row}`} className="seat-row">
                    <span className="row-num">{row}</span>
                    {['A', 'B'].map(col => {
                      const seatId = `${row}${col}`;
                      const isBooked = flightDetails?.booked_seats.includes(seatId);
                      const isSelected = selectedSeat === seatId;
                      return (
                        <button
                          key={seatId}
                          type="button"
                          className={`seat-btn ${isSelected ? 'selected' : ''}`}
                          disabled={isBooked}
                          onClick={() => setSelectedSeat(seatId)}
                        >
                          {seatId}
                        </button>
                      );
                    })}
                    <div className="aisle"></div>
                    {['C', 'D'].map(col => {
                      const seatId = `${row}${col}`;
                      const isBooked = flightDetails?.booked_seats.includes(seatId);
                      const isSelected = selectedSeat === seatId;
                      return (
                        <button
                          key={seatId}
                          type="button"
                          className={`seat-btn ${isSelected ? 'selected' : ''}`}
                          disabled={isBooked}
                          onClick={() => setSelectedSeat(seatId)}
                        >
                          {seatId}
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>

              <div className="seat-legend">
                <div className="legend-item"><div className="legend-box available"></div> Available</div>
                <div className="legend-item"><div className="legend-box selected"></div> Selected</div>
                <div className="legend-item"><div className="legend-box booked"></div> Occupied</div>
              </div>
            </div>

            <form onSubmit={handleConfirmBooking}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.25rem' }}>
                <div className="input-group">
                  <label>Passenger Name</label>
                  <input
                    type="text"
                    required
                    value={passengerName}
                    onChange={e => setPassengerName(e.target.value)}
                  />
                </div>
                <div className="input-group">
                  <label>Email Address</label>
                  <input
                    type="email"
                    required
                    value={passengerEmail}
                    onChange={e => setPassengerEmail(e.target.value)}
                  />
                </div>
              </div>

              <div style={{ background: '#f1f5f9', padding: '1rem', borderRadius: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
                <div>
                  <div style={{ fontSize: '0.8rem', color: '#64748b' }}>Selected Seat</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#1e3a8a' }}>{selectedSeat || 'None'}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '0.8rem', color: '#64748b' }}>Total Fare</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 800 }}>{priceLabel(selectedFlight)}</div>
                </div>
              </div>

              <button
                type="submit"
                className="btn-primary"
                style={{ width: '100%', height: '48px', fontSize: '1rem' }}
                disabled={!selectedSeat}
              >
                Confirm Reservation (Atomic ACID Lock)
              </button>
            </form>
          </div>
        </div>
      )}

      {/* My Bookings Modal */}
      {showMyBookings && (
        <div className="modal-backdrop">
          <div className="modal-content" style={{ maxWidth: '600px' }}>
            <div className="modal-header">
              <h3 style={{ fontSize: '1.25rem', fontWeight: 700 }}>My Bookings</h3>
              <button className="close-btn" onClick={() => setShowMyBookings(false)}>✕</button>
            </div>

            <div className="bookings-list">
              {myBookings.length === 0 ? (
                <p style={{ textAlign: 'center', color: '#64748b', padding: '2rem' }}>No bookings found yet.</p>
              ) : (
                myBookings.map(b => (
                  <div key={b.id} className="booking-ticket" style={{ opacity: b.status === 'CANCELLED' ? 0.6 : 1 }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ fontWeight: 800, fontSize: '1.05rem', color: '#1e3a8a' }}>{b.booking_ref}</span>
                        <span style={{
                          fontSize: '0.7rem',
                          fontWeight: 700,
                          padding: '0.15rem 0.5rem',
                          borderRadius: 9999,
                          background: b.status === 'CONFIRMED' ? '#dcfce7' : '#fee2e2',
                          color: b.status === 'CONFIRMED' ? '#15803d' : '#dc2626'
                        }}>
                          {b.status}
                        </span>
                      </div>
                      <div style={{ fontSize: '0.9rem', fontWeight: 600, marginTop: '0.25rem' }}>
                        {b.flight_number}: {b.origin} → {b.destination}
                      </div>
                      <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
                        Seat: <strong style={{ color: '#0f172a' }}>{b.seat_number}</strong> • Passenger: {b.passenger_name}
                      </div>
                      {b.duffel_order_id && (
                        <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginTop: '0.2rem' }}>
                          Duffel Order: {b.duffel_order_id}
                        </div>
                      )}
                    </div>

                    {b.status === 'CONFIRMED' && (
                      <button className="btn-cancel" onClick={() => handleCancelBooking(b.id)}>
                        Cancel
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {toast && (
        <div className="toast-container">
          <div className={`toast ${toast.type}`}>
            {toast.message}
          </div>
        </div>
      )}
    </div>
  );
}
