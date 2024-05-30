import sqlite3


def delete_facultyhub_table():
    # Connect to the database
    conn = sqlite3.connect(
        "database.db"
    )  # Replace 'database.db' with your actual database name
    cursor = conn.cursor()

    try:
        # Drop the facultyhub table if it exists
        cursor.execute("DROP TABLE IF EXISTS facultyhub")
        conn.commit()
        print("Table 'facultyhub' deleted successfully.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Close the database connection
        conn.close()


# Call the function to delete the table
delete_facultyhub_table()
