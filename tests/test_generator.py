from tests.synthetic.generate import generate


def test_planted_set_is_present_for_india_and_uae():
    for country in ("IN", "AE"):
        pack = generate(200, country, 1)
        rules = {p["rule"] for p in pack["planted"]}
        assert rules >= {"DUP_EXACT", "DUP_FUZZY", "DUP_VENDOR", "BANK_CHANGE_PAY", "CREDIT_UNAPPLIED"}
        assert pack["meta"]["currency"] == ("INR" if country == "IN" else "AED")
        assert pack["meta"]["payments"] >= 20
