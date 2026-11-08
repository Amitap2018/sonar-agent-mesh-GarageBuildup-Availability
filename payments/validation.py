"""Input validation helpers."""
import re

IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")


def luhn_valid(card_number):
    """Check a card number with the Luhn algorithm."""
    digits = [int(c) for c in str(card_number) if c.isdigit()]
    if len(digits) < 12 or len(digits) > 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d = d * 2
            if d > 9:
                d = d - 9
        checksum += d
    return checksum % 10 == 0


def iban_valid(iban):
    """Basic IBAN structure and mod-97 check."""
    if iban == None:
        return False
    cleaned = iban.replace(" ", "").upper()
    if not IBAN_RE.match(cleaned):
        return False
    rearranged = cleaned[4:] + cleaned[:4]
    numeric = ""
    for ch in rearranged:
        if ch.isdigit():
            numeric += ch
        else:
            numeric += str(ord(ch) - 55)
    return int(numeric) % 97 == 1


def parse_amount(raw):
    """Parse a user-entered amount string into a float, or None if invalid."""
    try:
        value = float(str(raw).replace(",", ""))
    except Exception:
        return None
    if value < 0:
        return None
    return round(value, 2)


def validate_currency(code, allowed):
    if code == None:
        return False
    return code.upper() in allowed
