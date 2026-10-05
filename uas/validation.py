import re

EMAIL_RE = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+$", re.IGNORECASE)
PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")
VALID_ROLES = {"student", "teacher", "admin"}


class InputValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__(next(iter(errors.values()), "Invalid input"))


def clean_text(value, field, *, minimum=1, maximum=255):
    value = (value or "").strip()
    if not minimum <= len(value) <= maximum:
        raise InputValidationError({field: f"Enter between {minimum} and {maximum} characters."})
    return value


def validate_email(value, role):
    email = (value or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise InputValidationError({"email": "Enter a valid email address."})
    allowed = {
        "student": "student.mmu.edu.my",
        "teacher": "mmu.edu.my",
    }.get(role)
    if allowed and email.rsplit("@", 1)[1] != allowed:
        label = "@student.mmu.edu.my" if role == "student" else "@mmu.edu.my"
        raise InputValidationError({"email": f"Use your university {label} email."})
    return email


def validate_phone(value):
    phone = re.sub(r"[\s().-]", "", value or "")
    if not PHONE_RE.fullmatch(phone):
        raise InputValidationError({"phone_number": "Enter a phone number with 7 to 15 digits."})
    return phone


def validate_account(*, role, username, email, phone_number):
    if role not in VALID_ROLES:
        raise InputValidationError({"role": "Select a valid account type."})
    return {
        "username": clean_text(username, "username", maximum=100),
        "email": validate_email(email, role),
        "phone_number": validate_phone(phone_number),
    }


def parse_positive_int(value, field, *, minimum=1, maximum=1000000):
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise InputValidationError({field: "Enter a valid number."}) from exc
    if not minimum <= number <= maximum:
        raise InputValidationError({field: f"Enter a value from {minimum} to {maximum}."})
    return number


def validate_purpose(value):
    return clean_text(value, "purpose", maximum=500)


def validate_password(value):
    password = value or ""
    encoded_length = len(password.encode("utf-8"))
    if len(password) < 12 or encoded_length > 72:
        raise InputValidationError({"password": "Use at least 12 characters and no more than 72 UTF-8 bytes."})
    return password


def validate_search(value):
    value = (value or "").strip()
    if len(value) > 100:
        raise InputValidationError({"search": "Search text must be 100 characters or fewer."})
    return value
