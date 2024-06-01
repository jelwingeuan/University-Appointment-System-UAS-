
from create_tables import get_db_connection
from datetime import datetime, timedelta

def calendar_record(lecturer, event_title, event_date, start_time, end_time):
    con = get_db_connection()
    cur = con.cursor()
    
    cur.execute("""
        INSERT INTO calendar (lecturer, event_title, event_date, start_time, end_time)
        VALUES (?, ?, ?, ?, ?)
    """, (lecturer, event_title, event_date, start_time, end_time))
    
    con.commit()
    con.close()


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
    
    for i in range(1,repeat_count):
        if repeat_type == "daily":
            event_date += timedelta(days=1)
        elif repeat_type == "weekly":
            event_date += timedelta(weeks=1)
        elif repeat_type == "monthly":
            new_month = event_date.month + 1
            new_year = event_date.year
            if new_month > 12:
                new_month = 1
                new_year += 1
            event_date = event_date.replace(year=new_year, month=new_month)
            
        cur.execute("""
            INSERT INTO calendar (lecturer, event_title, event_date, start_time, end_time)
        """, (lecturer, event_title, event_date.strftime("%Y-%m-%d"), start_time, end_time)
        )
        
    con.commit()
    con.close()
    return True

