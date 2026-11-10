"""Pricing entry point of the sample service: the shipped fee code plus the runtime config that can drift."""
import sys
sys.path.insert(0, ".")
from payments.fees import card_fee

def priced(amount, card_type, international, cfg):
    fee = card_fee(amount, card_type, international)
    return round(fee * (1 + cfg.get("fee_markup_pct", 0) / 100.0), 2)
