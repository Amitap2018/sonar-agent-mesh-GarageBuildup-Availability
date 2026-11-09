import json, loop
def test_low_risk_goes_to_agent():
    p = {"tier": 2, "high_risk_threshold": 70, "sensitive_paths": ["payments/"]}
    s = loop.risk_score(p, ["payments/fees.py", "tests/test_fees.py"])
    assert s == 30 + 6 + 20 and loop.decide(p, s) == "auto"
def test_tier1_always_human():
    p = {"tier": 1, "high_risk_threshold": 70}
    assert loop.decide(p, loop.risk_score(p, ["README.md"])) == "human"
def test_large_change_goes_to_human():
    p = {"tier": 2, "high_risk_threshold": 70, "sensitive_paths": ["payments/"]}
    s = loop.risk_score(p, [f"payments/f{i}.py" for i in range(12)])
    assert s >= 70 and loop.decide(p, s) == "human"
