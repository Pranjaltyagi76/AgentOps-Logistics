"""Judge calibration statistics."""

import pytest

from app.domain.calibration import MIN_ITEMS, agreement, cohen_kappa, spearman


def test_perfect_agreement_meets_the_bar() -> None:
    scores = [i / (MIN_ITEMS - 1) for i in range(MIN_ITEMS)]
    result = agreement(scores, scores)
    assert result.mean_absolute_error == 0 and result.spearman == 1.0
    assert result.cohen_kappa == 1.0 and result.good_agreement == 1.0
    assert result.meets_bar and result.reasons == []


def test_too_few_items_never_meet_the_bar() -> None:
    result = agreement([0.1, 0.9], [0.1, 0.9])
    assert not result.meets_bar and "only 2 labelled items" in result.reasons[0]


def test_a_judge_that_inverts_the_ranking_fails() -> None:
    human = [i / (MIN_ITEMS - 1) for i in range(MIN_ITEMS)]
    result = agreement(human, list(reversed(human)))
    assert result.spearman == -1.0 and not result.meets_bar
    assert any("Spearman" in r for r in result.reasons)


def test_ties_use_average_ranks() -> None:
    assert spearman([1, 2, 2, 3], [1, 2, 2, 3]) == pytest.approx(1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) is None  # one side is constant


def test_kappa() -> None:
    assert cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert cohen_kappa([True, True], [True, True]) is None  # one class only
    assert cohen_kappa([True, False, True, False], [False, True, False, True]) == -1.0


def test_lengths_must_match() -> None:
    with pytest.raises(ValueError):
        agreement([0.1], [0.1, 0.2])
