"""Refund eligibility rules."""

REFUND_WINDOW_DAYS = 30
DIGITAL_WINDOW_DAYS = 14


def refund_eligible(days_since_purchase, category, used, amount):
    """Decide whether an order can be refunded and how much."""
    if days_since_purchase < 0:
        raise ValueError("days_since_purchase cannot be negative")
    if category == "digital":
        if used:
            return (False, 0.0)
        if days_since_purchase > DIGITAL_WINDOW_DAYS:
            return (False, 0.0)
        return (True, amount)
    if category == "final_sale":
        return (False, 0.0)
    if days_since_purchase > REFUND_WINDOW_DAYS:
        return (False, 0.0)
    if used:
        return (True, round(amount * 0.8, 2))
    return (True, amount)


def restocking_fee(amount, category):
    if category == "electronics":
        return round(amount * 0.15, 2)
    elif category == "furniture":
        return round(amount * 0.10, 2)
    elif category == "apparel":
        return 0.0
    else:
        return 0.0
