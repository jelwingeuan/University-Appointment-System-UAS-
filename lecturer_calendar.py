
from create_tables import get_db_connection

def set_availability(lecturer, available_date, available_hour_start, available_hour_end, time_slot_start, time_slot_end, slot_duration):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO calendar (lecturer, available_date, available_hour_start, available_hour_end, time_slot_start, time_slot_end, slot_duration)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (lecturer, available_date, available_hour_start, available_hour_end, time_slot_start, time_slot_end, slot_duration))
    
    conn.commit()
    conn.close()


def get_available_slots(lecturer, available_date):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT available_hour_start, available_hour_end, time_slot_start, time_slot_end, slot_duration
        FROM calendar
        WHERE lecturer_id = ? AND available_date = ?
    """, (lecturer, available_date))
    
    slots = cursor.fetchall()
    conn.close()
    return slots


def book_slot(student, lecturer, booking_date, time_slot_start, time_slot_end):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if the slot is available
    cursor.execute('''
        SELECT COUNT(*) FROM lecturer_availability
        WHERE lecturer = ? AND available_date = ? AND time_slot_start = ? AND time_slot_end = ?
    ''', (lecturer, booking_date, time_slot_start, time_slot_end))
    count = cursor.fetchone()[0]

    if count == 0:
        conn.close()
        return "Slot is not available"

    # Book the slot
    cursor.execute('''
        INSERT INTO bookings (student_id, lecturer_id, booking_date, time_slot_start, time_slot_end)
        VALUES (?, ?, ?, ?, ?)
    ''', (student, lecturer, booking_date, time_slot_start, time_slot_end))
    conn.commit()
    conn.close()
    return "Booking successful"

