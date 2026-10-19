import pytest

from analyzer.hotspots import score_file

from hotspot_contract import check_contract
from reference_scorer import ignores_churn, reference_score


def test_the_contract_is_satisfiable_reference_scorer_passes():
    check_contract(reference_score)


def test_the_contract_catches_a_scorer_that_ignores_churn():
    with pytest.raises(AssertionError):
        check_contract(ignores_churn)


def test_your_score_file_satisfies_the_contract():
    """Skipped while score_file is the TODO stub; becomes a real check once you implement it."""
    try:
        check_contract(score_file)
    except NotImplementedError:
        pytest.skip("TODO(user): score_file not implemented yet")
