from functools import wraps

from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import mysql.connector
from datetime import datetime
import os

app = Flask(__name__, template_folder='.', static_folder='.')
app.secret_key = os.getenv("SECRET_KEY", "dev_key")
CORS(app)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", 'admin123')

# Database configuration
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'animesh',
    'database': 'hotel_booking_db'
}

# Get database connection
def get_db_connection():
    return mysql.connector.connect(**db_config)

def require_admin(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get('is_admin'):
            return jsonify({'success': False, 'error': 'Admin authentication required.'}), 401
        return func(*args, **kwargs)
    return wrapper

# Home page
@app.route('/')
def index():
    return render_template('hotel_frontend.html')

@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    return jsonify({
        'success': True,
        'is_admin': bool(session.get('is_admin')),
        'username': session.get('admin_username')
    })

@app.route('/api/auth/login', methods=['POST'])
def admin_login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session['is_admin'] = True
        session['admin_username'] = username
        return jsonify({'success': True, 'message': 'Admin login successful.'})

    return jsonify({'success': False, 'error': 'Invalid admin credentials.'}), 401

@app.route('/api/auth/logout', methods=['POST'])
def admin_logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out.'})

# Get all available rooms
@app.route('/api/rooms', methods=['GET'])
def get_rooms():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM rooms WHERE availability = 'Available'")
        rooms = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'rooms': rooms})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Add new room (Admin)
@app.route('/api/rooms/add', methods=['POST'])
@require_admin
def add_room():
    try:
        data = request.json
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "INSERT INTO rooms (room_number, room_type, price, availability) VALUES (%s, %s, %s, %s)"
        cursor.execute(query, (data['room_number'], data['room_type'], data['price'], 'Available'))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Room added successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Book a room
@app.route('/api/bookings/create', methods=['POST'])
def create_booking():
    try:
        data = request.json
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check room availability
        cursor.execute("SELECT availability FROM rooms WHERE room_id = %s", (data['room_id'],))
        room = cursor.fetchone()
        
        if not room or room[0] != 'Available':
            return jsonify({'success': False, 'error': 'Room not available'})
        
        # Insert customer
        query = "INSERT INTO customers (name, email, phone, id_proof) VALUES (%s, %s, %s, %s)"
        cursor.execute(query, (data['name'], data['email'], data['phone'], data['id_proof']))
        customer_id = cursor.lastrowid
        
        # Create booking
        query = "INSERT INTO bookings (customer_id, room_id, check_in, check_out, total_amount, status) VALUES (%s, %s, %s, %s, %s, %s)"
        cursor.execute(query, (customer_id, data['room_id'], data['check_in'], data['check_out'], data['total_amount'], 'Confirmed'))
        booking_id = cursor.lastrowid
        
        # Update room availability
        cursor.execute("UPDATE rooms SET availability = 'Booked' WHERE room_id = %s", (data['room_id'],))
        
        # Create payment record
        query = "INSERT INTO payments (booking_id, amount, payment_status) VALUES (%s, %s, %s)"
        cursor.execute(query, (booking_id, data['total_amount'], 'Pending'))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Booking created successfully', 'booking_id': booking_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Get all bookings
@app.route('/api/bookings', methods=['GET'])
@require_admin
def get_bookings():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
        SELECT b.booking_id, c.name, c.email, c.phone, r.room_number, r.room_type, 
               b.check_in, b.check_out, b.total_amount, b.status, p.payment_status
        FROM bookings b
        JOIN customers c ON b.customer_id = c.customer_id
        JOIN rooms r ON b.room_id = r.room_id
        JOIN payments p ON b.booking_id = p.booking_id
        ORDER BY b.booking_date DESC
        """
        cursor.execute(query)
        bookings = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'bookings': bookings})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Cancel booking
@app.route('/api/bookings/cancel/<int:booking_id>', methods=['PUT'])
@require_admin
def cancel_booking(booking_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get room_id from booking
        cursor.execute("SELECT room_id FROM bookings WHERE booking_id = %s", (booking_id,))
        room = cursor.fetchone()
        
        # Update booking status
        cursor.execute("UPDATE bookings SET status = 'Cancelled' WHERE booking_id = %s", (booking_id,))
        
        # Update room availability
        cursor.execute("UPDATE rooms SET availability = 'Available' WHERE room_id = %s", (room[0],))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Booking cancelled successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Generate report
@app.route('/api/reports', methods=['GET'])
@require_admin
def generate_report():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Total bookings
        cursor.execute("SELECT COUNT(*) as total_bookings FROM bookings WHERE status = 'Confirmed'")
        total_bookings = cursor.fetchone()['total_bookings']
        
        # Total revenue
        cursor.execute("SELECT SUM(total_amount) as total_revenue FROM bookings WHERE status = 'Confirmed'")
        total_revenue = cursor.fetchone()['total_revenue'] or 0
        
        # Occupancy rate
        cursor.execute("SELECT COUNT(*) as total_rooms FROM rooms")
        total_rooms = cursor.fetchone()['total_rooms']
        cursor.execute("SELECT COUNT(*) as booked_rooms FROM rooms WHERE availability = 'Booked'")
        booked_rooms = cursor.fetchone()['booked_rooms']
        occupancy_rate = (booked_rooms / total_rooms * 100) if total_rooms > 0 else 0
        
        cursor.close()
        conn.close()
        
        report = {
            'total_bookings': total_bookings,
            'total_revenue': float(total_revenue),
            'occupancy_rate': round(occupancy_rate, 2),
            'total_rooms': total_rooms,
            'booked_rooms': booked_rooms
        }
        
        return jsonify({'success': True, 'report': report})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True, port=5000)