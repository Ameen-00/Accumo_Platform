from decimal import Decimal
from uuid import uuid4

from accumo_canonical.identity import VendorSnap, propose
from accumo_canonical.normalise import normalise_name


def _v(name: str, **kw) -> VendorSnap:
    return VendorSnap(
        id=uuid4(),
        name=name,
        name_normalised=normalise_name(name),
        tax_id=kw.get("tax_id"),
        registration_id=kw.get("registration_id"),
        account_norms=kw.get("account_norms") or [],
    )


def test_same_tax_id_auto_merges():
    a = _v("ABC Traders Pvt Ltd", tax_id="32AABCA1111B1Z2")
    b = _v("A B C Trading FZE", tax_id="32AABCA1111B1Z2")
    props = propose([a, b])
    merged = [p for p in props if len(p.member_ids) == 2]
    assert len(merged) == 1
    assert merged[0].method == "tax_id"
    assert merged[0].needs_review is False
    assert merged[0].confidence == Decimal("1.00")


def test_same_bank_auto_merges():
    a = _v("Southern Steels", account_norms=["aaa"])
    b = _v("Southern Steels Co", account_norms=["aaa"])
    merged = [p for p in propose([a, b]) if len(p.member_ids) == 2][0]
    assert merged.method == "bank"
    assert merged.needs_review is False


def test_identical_normalised_name_auto_merges():
    a = _v("ABC Traders Pvt Ltd")
    b = _v("ABC Trading FZE")
    assert a.name_normalised == b.name_normalised == "ABC"
    merged = [p for p in propose([a, b]) if len(p.member_ids) == 2][0]
    assert merged.method == "name_exact"
    assert merged.needs_review is False


def test_close_names_go_to_review_not_auto():
    a = _v("Southern Steels")
    b = _v("Southern Steel")
    props = propose([a, b])
    pending = [p for p in props if p.needs_review]
    assert len(pending) == 1
    assert pending[0].method == "name_fuzzy"
    assert pending[0].confidence < Decimal("0.85")


def test_unrelated_names_stay_apart():
    a = _v("Malabar Oils")
    b = _v("Cochin Packing")
    props = propose([a, b])
    assert all(len(p.member_ids) == 1 for p in props)
    assert all(p.needs_review is False for p in props)
