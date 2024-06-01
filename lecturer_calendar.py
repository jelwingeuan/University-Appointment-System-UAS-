
from create_tables import get_db_connection
import datetime

def event_record(student, lecturer, event_title, event_date, start_time, end_time, purpose, status="Pending"):
    con = get_db_connection()
    cur = con.cursor()
    
    cur.execute("""
        INSERT INTO appointments (student, lecturer, event_title, event_date, start_time, end_time, purpose, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (student, lecturer, event_title, event_date, start_time, end_time, purpose, status))
    
    con.commit()
    con.close()


def event_repeat(id, repeat_type, repeat_until=None):
    con = get_db_connection()
    cur = con.cursor()
    
    cur.execute("""SELECT *
                FROM appointments WHERE id = ?""", (id,)
                )
    appointment = cur.fetchone()
    
    if not appointment:
        print("Appointment not found.")
        return

    student, lecturer, event_title, event_date, start_time, end_time, purpose, status = appointment[1:]
    
    if repeat_type == "None":
        return

    repeat_date = datetime.datetime.strptime(event_date, "%Y-%m-%d")
    repeat_until = datetime.datetime.strptime(repeat_until, "%Y-%m-%d") if repeat_until else None
    
    while True:
        if repeat_type == "Daily":
            repeat_date += datetime.timedelta(days=1)
        elif repeat_type == "Weekly":
            repeat_date += datetime.timedelta(weeks=1)
        elif repeat_type == "Monthly":
            month = repeat_date.month + 1 if repeat_date.month < 12 else 1
            year = repeat_date.year + 1 if month == 1 else repeat_date.year
            repeat_date = repeat_date.replace(year=year, month=month)
        else:
            print("Invalid repeat type.")
            return

        if repeat_until and repeat_date > repeat_until:
            break
        
        cur.execute("""
            INSERT INTO appointments (student, lecturer, event_title, event_date, start_time, end_time, purpose, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (student, lecturer, event_title, repeat_date.strftime("%Y-%m-%d"), start_time, end_time, purpose, status))
        
        cur.execute("""
        INSERT INTO repeat_appointments (booking_id, repeat_type, repeat_until)
        VALUES (?, ?, ?)
    """, (id, repeat_type, repeat_until.strftime("%Y-%m-%d") if repeat_until else None))
        
        con.commit()
        con.close()
    
    

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
        INSERT INTO bookings (student, lecturer, booking_date, time_slot_start, time_slot_end)
        VALUES (?, ?, ?, ?, ?)
    ''', (student, lecturer, booking_date, time_slot_start, time_slot_end))
    conn.commit()
    conn.close()
    return "Booking successful"

