University Appointment System (UAS)

The University Appointment System (UAS) is a web application built with Flask, designed to manage appointments within a university setting. It allows students, faculty, and staff to schedule and manage appointments efficiently.

## Features

- **User Authentication**: Users can sign up for accounts and log in securely using bcrypt for password hashing.
- **Appointment Booking**: Students can book appointments with faculty or staff members for various purposes such as academic advising, office hours, or consultations.
- **Faculty Hub Creation**: Faculty members can create hubs for managing their appointments, specifying their availability and location.
- **Admin Panel**: Administrators have access to an admin panel where they can manage user accounts, faculty hubs, and other system settings.
- **Database Integration**: UAS integrates with SQLite for data storage, ensuring reliable and efficient data management.

## Installation

1. Clone the repository:

    ```bash
    git clone https://github.com/jelwingeuan/University-Appointment-System-UAS
    ```

2. Navigate to the project directory:

    ```bash
    cd uas
    ```

3. Install dependencies:

    ```bash
    pip install -r requirements.txt
    ```

4. Initialize the database:

    ```bash
    python initialize_database.py
    ```

5. Run the application:

    ```bash
    python app.py
    ```

6. Access the application in your web browser at `http://localhost:6969`.

- Visit the home page to get started.
- Sign up for an account or log in if you already have one.
- Faculty members can create hubs to manage their availability and appointments.
- Administrators can access the admin panel for advanced management options, including user accounts and system settings.
