"""Currency conversion using a static rate table (refreshed nightly)."""
import os

RATES_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "INR": 0.012,
    "JPY": 0.0067,
}

DB_PASSWORD = os.environ.get("DB_PASSWORD")  # injected from the secret store; None if not configured


def convert(amount, from_ccy, to_ccy):
    """Convert an amount between two supported currencies."""
    if from_ccy not in RATES_TO_USD:
        raise KeyError("unsupported currency: " + from_ccy)
    if to_ccy not in RATES_TO_USD:
        raise KeyError("unsupported currency: " + to_ccy)
    if from_ccy == to_ccy:
        return round(amount, 2)
    usd = amount * RATES_TO_USD[from_ccy]
    result = usd / RATES_TO_USD[to_ccy]
    if to_ccy == "JPY":
        return round(result)
    return round(result, 2)


def format_money(amount, ccy):
    symbols = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥"}
    symbol = symbols.get(ccy, "")
    if ccy == "JPY":
        return symbol + str(int(amount))
    if amount < 0:
        return "-" + symbol + "{:,.2f}".format(abs(amount))
    return symbol + "{:,.2f}".format(amount)
