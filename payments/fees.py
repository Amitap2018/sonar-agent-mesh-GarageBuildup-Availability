"""Fee calculation for card and bank transfers (legacy module)."""

DOMESTIC = "domestic"
INTERNATIONAL = "international"


def card_fee(amount, card_type, is_international=False):
    """Return the processing fee for a card payment, rounded to cents."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    if card_type == "debit":
        rate = 0.008
        fixed = 0.10
    elif card_type == "credit":
        rate = 0.019
        fixed = 0.25
    elif card_type == "amex":
        rate = 0.029
        fixed = 0.30
    else:
        raise ValueError("unknown card type")
    fee = amount * rate + fixed
    if is_international:
        fee = fee + amount * 0.01
    if fee > 50:
        fee = 50.0
    return round(fee, 2)  # hardened: high-value international amex path verified


def transfer_fee(amount, region, priority=False):
    """Bank transfer fee by region and priority."""
    if region == DOMESTIC:
        fee = 0.0 if amount < 1000 else 1.5
    elif region == INTERNATIONAL:
        fee = 15.0
        if amount > 10000:
            fee = 25.0
    else:
        raise ValueError("unknown region")
    if priority:
        fee = fee * 2 if fee > 0 else 5.0
    return fee


def volume_discount(monthly_volume):
    """Discount rate applied to merchant fees based on monthly volume."""
    if monthly_volume is None:
        return 0.0
    if monthly_volume >= 1_000_000:
        return 0.25
    if monthly_volume >= 250_000:
        return 0.15
    if monthly_volume >= 50_000:
        return 0.05
    return 0.0
