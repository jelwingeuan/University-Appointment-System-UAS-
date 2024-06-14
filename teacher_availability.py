from create_tables import get_db_connection
from datetime import date, datetime, timedelta

def availability_record(lecturer, appointment_date, start_time, end_time):
    con = get_db_connection()
    cur = con.cursor()
    
    cur.execute("""
        INSERT INTO availability (lecturer, appointment_date, start_time, end_time)
        VALUES (?, ?, ?, ?)
    """, (lecturer, appointment_date, start_time, end_time))
    
    con.commit()
    con.close()


def get_availability():
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("SELECT * FROM availability")
    availability = cur.fetchall()
    con.close()
    return availability


def increment_month(appointment_date, repeat_interval=1):
    new_month = appointment_date.month + repeat_interval
    new_year = appointment_date.year + (new_month - 1) // 12
    
    # Based on index of month
    new_month = (new_month - 1) % 12 + 1

    # Calculate the number of days in the new month
    days_in_month = [
        31,
        29 if new_month == 2 and (new_year % 4 == 0 and (new_year % 100 != 0 or new_year % 400 == 0)) else 28,
        31,
        30,
        31,
        30, 
        31,
        31,
        30,
        31,
        30,
        31
    ][new_month - 1]

    # Ensure the day is valid for the new month
    day = min(appointment_date.day, days_in_month)
    return appointment_date.replace(year=new_year, month=new_month, day=day)

def increment_month_for_31(appointment_date, repeat_interval=1):
    new_month = appointment_date.month
    new_year = appointment_date.year

    for _ in range(repeat_interval):
        new_month += 1
        if new_month > 12:
            new_month -= 12
            new_year += 1
        if new_month in [1, 3, 5, 7, 8, 10, 12]:
            break

    return appointment_date.replace(year=new_year, month=new_month, day=31)

def availability_repeat(appointment_date, start_time, end_time, repeat_type, repeat_interval, repeat_count):
    con = get_db_connection()
    cur = con.cursor()
    
    cur.execute("""
        SELECT *
        FROM availability
        WHERE appointment_date = ? AND start_time = ? AND end_time = ?
    """, (appointment_date, start_time, end_time))
    appointment = cur.fetchone()
    
    if appointment is None:
        con.close()
        print("Appointment not found")
        return None

    lecturer = appointment["lecturer"]
    
    try:
        appointment_date = datetime.strptime(appointment["appointment_date"], "%Y-%m-%d")
    except ValueError:
        con.close()
        print("Invalid date format. Expected YYYY-MM-DD.")
        return None
    
    if repeat_count == 1:
        con.close()
        return True
    
    for _ in range(1, repeat_count):
        if repeat_type == "No Repeat":
            # No change in appointment_date
            pass
        elif repeat_type == "Daily": 
            appointment_date += timedelta(days=repeat_interval)
        elif repeat_type == "Weekly":
            appointment_date += timedelta(weeks=repeat_interval)
        elif repeat_type == "Monthly":
            if appointment_date.day == 31:
                appointment_date = increment_month_for_31(appointment_date, repeat_interval)
            else:
                appointment_date = increment_month(appointment_date, repeat_interval)
        
        cur.execute("""
            INSERT INTO availability (lecturer, appointment_date, start_time, end_time)
            VALUES (?, ?, ?, ?)
        """, (lecturer, appointment_date.strftime("%Y-%m-%d"), start_time, end_time))
        
    con.commit()
    con.close()
    return True
