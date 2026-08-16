"""Ask once, never again -- the rule the whole of v2 rests on.

Arjun's criticism of v1 was that a match-match-match screen is just another
clerical reconciliation, and Zoho already does that without AI. These tests
guard the fix: a question is asked at the level of a pattern, once.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from accumo_rules.patterns import (
    BANK_ACCOUNT,
    CLUBBING,
    NARRATION,
    OBSERVED,
    TAUGHT,
    TDS,
    Pattern,
    confidence_for,
    learn_tds,
    merge,
    should_ask,
    tds_prior,
)


def test_asks_when_nothing_is_known():
    assert should_ask([], NARRATION) is True


def test_never_asks_the_same_question_twice():
    """The core rule. Once a person has been asked, that question is spent --
    whether or not the answer was useful. Asking again is a defect."""
    asked = Pattern(kind=NARRATION, value={}, asked_at=datetime.now(timezone.utc))
    assert should_ask([asked], NARRATION) is False


def test_does_not_ask_when_pulse_worked_it_out_itself():
    """Six matching payments is a habit, not a coincidence. Nobody should be
    interrupted to confirm what the data already says clearly."""
    sure = Pattern(kind=NARRATION, value={"text": "ABCTRD"},
                   source=OBSERVED, confidence=Decimal("0.900"), observations=6)
    assert should_ask([sure], NARRATION) is False


def test_still_asks_when_the_evidence_is_thin():
    weak = Pattern(kind=NARRATION, value={"text": "ABCTRD"},
                   source=OBSERVED, confidence=Decimal("0.600"), observations=2)
    assert should_ask([weak], NARRATION) is True


def test_questions_are_independent_per_kind():
    """Being asked about narration does not buy silence on bank account."""
    asked = Pattern(kind=NARRATION, value={}, asked_at=datetime.now(timezone.utc))
    assert should_ask([asked], NARRATION) is False
    assert should_ask([asked], BANK_ACCOUNT) is True


def test_unknown_kind_is_a_programming_error():
    with pytest.raises(ValueError):
        should_ask([], "not_a_kind")


def test_confidence_is_slow_on_purpose():
    """Two payments alike is a coincidence; six is a habit. 0.850 is the point
    where Pulse stops asking, so this curve decides what buys silence."""
    assert confidence_for(1) < confidence_for(2) < confidence_for(4)
    assert confidence_for(6) >= Decimal("0.850")
    assert should_ask([Pattern(NARRATION, {}, OBSERVED, confidence_for(6), 6)], NARRATION) is False
    assert should_ask([Pattern(NARRATION, {}, OBSERVED, confidence_for(4), 4)], NARRATION) is True


def test_teaching_beats_observation():
    observed = Pattern(CLUBBING, {"clubs": False}, OBSERVED, Decimal("0.750"), 4)
    taught = Pattern(CLUBBING, {"clubs": True}, TAUGHT, Decimal("0.900"))
    out = merge(observed, taught)
    assert out.value == {"clubs": True}
    assert out.source == TAUGHT
    # The evidence Pulse gathered is kept -- it is what we check the teaching
    # against later. A learning system that forgets its own data cannot notice
    # when a user was wrong.
    assert out.observations == 4


def test_observation_does_not_overwrite_teaching():
    taught = Pattern(CLUBBING, {"clubs": True}, TAUGHT, Decimal("0.900"), 2)
    later = Pattern(CLUBBING, {"clubs": False}, OBSERVED, Decimal("0.750"), 3)
    out = merge(taught, later)
    assert out.value == {"clubs": True}
    assert out.source == TAUGHT
    assert out.observations == 5


# ------------------------------------------------------------------- TDS ----

def test_tds_is_learned_per_nature_not_per_supplier():
    """The rate follows the nature of the work. The same supplier can invoice
    contract work at one section and professional fees at another -- applying a
    remembered supplier rate to the wrong invoice is confidently wrong, which is
    worse than leaving it unresolved."""
    p = learn_tds(None, "contract", "194C", Decimal("2.0"), taught=True)
    p = learn_tds(p, "professional", "194J", Decimal("10.0"), taught=True)

    assert tds_prior([p], "contract")["rate"] == "2.0"
    assert tds_prior([p], "contract")["section"] == "194C"
    assert tds_prior([p], "professional")["rate"] == "10.0"


def test_unknown_nature_returns_nothing_rather_than_guessing():
    """None means 'not learned'. It must never be read as 'no TDS applies'."""
    p = learn_tds(None, "contract", "194C", Decimal("2.0"), taught=True)
    assert tds_prior([p], "rent") is None
    assert tds_prior([], "contract") is None


def test_taught_tds_is_trusted_more_than_observed():
    seen = learn_tds(None, "contract", "194C", Decimal("2.0"), taught=False)
    told = learn_tds(None, "contract", "194C", Decimal("2.0"), taught=True)
    assert told.confidence > seen.confidence
    assert told.source == TAUGHT
