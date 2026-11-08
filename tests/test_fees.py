from payments.fees import card_fee


def test_debit_fee():
    assert card_fee(100, "debit") == 0.9
