"""Phone number normalization utility

Normalizes phone numbers to digits-only format (6-15 digits).
Used consistently across signup, settings updates, and admin user creation.
"""


def normalize_phone_number(phone_number: str | None) -> str | None:
    """Normalize phone number to digits-only format (6-15 digits)

    Args:
        phone_number: Phone number string (may contain non-digit characters)

    Returns:
        Normalized phone number (digits only) or None if invalid/empty

    Raises:
        ValueError: If phone number has invalid length after normalization
    """
    if not phone_number:
        return None

    # Remove all non-digit characters
    phone_digits = "".join(filter(str.isdigit, phone_number))

    # Validate length (6-15 digits)
    if phone_digits and (len(phone_digits) < 6 or len(phone_digits) > 15):
        raise ValueError("Phone number must be 6-15 digits")

    # Return None for empty strings, otherwise return digits-only
    return phone_digits if phone_digits else None
