from create_tables import get_db_connection
from datetime import date, datetime, timedelta

def calendar_record(lecturer, event_title, event_date, start_time, end_time):
    con = get_db_connection()
    cur = con.cursor()
    
    cur.execute("""
        INSERT INTO calendar (lecturer, event_title, event_date, start_time, end_time)
        VALUES (?, ?, ?, ?, ?)
    """, (lecturer, event_title, event_date, start_time, end_time))
    
    con.commit()
    con.close()


def increment_month(event_date, repeat_interval=1):
    new_month = event_date.month + repeat_interval
    new_year = event_date.year + (new_month - 1) // 12
    
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
    day = min(event_date.day, days_in_month)
    return event_date.replace(year=new_year, month=new_month, day=day)



def increment_month_for_31(event_date):
    months_with_31_days = [1, 3, 5, 7, 8, 10, 12]
    new_month = event_date.month
    new_year = event_date.year

    while True:
        new_month += 1
        if new_month > 12:
            new_month = 1
            new_year += 1

        if new_month in months_with_31_days:
            return event_date.replace(year=new_year, month=new_month, day=31)


def increment_month_for_30(event_date):
    months_with_30_days = [4, 6, 9, 11]
    new_month = event_date.month
    new_year = event_date.year

    while True:
        new_month += 1
        if new_month > 12:
            new_month = 1
            new_year += 1

        if new_month in months_with_30_days:
            return event_date.replace(year=new_year, month=new_month, day=30)


def calendar_repeat(event_title, repeat_type, repeat_count):
    con = get_db_connection()
    cur = con.cursor()
    
    cur.execute("""SELECT *
                FROM calendar WHERE event_title = ?""", (event_title,)
                )
    event = cur.fetchone()
    
    if event is None:
        con.close()
        print("Event not found")
        return None

    lecturer = event["lecturer"]
    start_time = event["start_time"]
    end_time = event["end_time"]
    
    try:
        event_date = datetime.strptime(event["event_date"], "%Y-%m-%d")
    except ValueError:
        con.close()
        print("Invalid date format. Expected YYYY-MM-DD.")
        return None
    
    if repeat_count == 1:
        con.close()
        return True
    
    for i in range(1, repeat_count):
        if repeat_type == "No Repeat":
            event_date = event_date
        elif repeat_type == "Daily": 
            event_date += timedelta(days=1)
        elif repeat_type == "Weekly":
            event_date += timedelta(weeks=1)
        elif repeat_type == "Monthly":
            if event_date.day == 31:
                event_date = increment_month_for_31(event_date)
            elif event_date.day == 30:
                event_date = increment_month_for_30(event_date)
            else:
                event_date = increment_month(event_date)
            
        cur.execute("""
            INSERT INTO calendar (lecturer, event_title, event_date, start_time, end_time)
        """, (lecturer, event_title, event_date.strftime("%Y-%m-%d"), start_time, end_time)
        )
        
    con.commit()
    con.close()
    return True