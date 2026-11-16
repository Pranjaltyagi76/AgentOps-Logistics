"""Agreement between the LLM judge and hand labels (benchmark.md §12). Pure, no I/O.

The judge stays advisory until a calibration run on >= MIN_ITEMS hand-labelled replies meets
every threshold below; `scripts/judge_calibration.py` produces the inputs.
"""

from dataclasses import asdict, dataclass

MIN_ITEMS = 20
GOOD_THRESHOLD = 0.7  # a reply scored >= 0.7 counts as "good"
# Proposed bar for letting the judge affect scores (benchmark.md §12).
MAX_MAE = 0.15
MIN_SPEARMAN = 0.6
MIN_KAPPA = 0.6


@dataclass(frozen=True)
class Agreement:
    n: int
    mean_absolute_error: float | None
    spearman: float | None
    good_agreement: float | None  # share where both call it good, or both not good
    cohen_kappa: float | None
    meets_bar: bool
    reasons: list[str]

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def _ranks(values: list[float]) -> list[float]:
    """Average ranks (ties share the mean of their positions), 1-based."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        mean_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = mean_rank
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None  # a constant side: correlation undefined
    return cov / (vx * vy) ** 0.5


def spearman(xs: list[float], ys: list[float]) -> float | None:
    return _pearson(_ranks(xs), _ranks(ys))


def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected == 1:
        return None  # both raters gave one class only: kappa undefined
    return (observed - expected) / (1 - expected)


def agreement(human: list[float], judge: list[float]) -> Agreement:
    if len(human) != len(judge):
        raise ValueError("human and judge scores must pair up")
    n = len(human)
    mae = sum(abs(h - j) for h, j in zip(human, judge, strict=True)) / n if n else None
    rho = spearman(human, judge)
    good_h = [h >= GOOD_THRESHOLD for h in human]
    good_j = [j >= GOOD_THRESHOLD for j in judge]
    agree = sum(1 for x, y in zip(good_h, good_j, strict=True) if x == y) / n if n else None
    kappa = cohen_kappa(good_h, good_j)

    reasons = []
    if n < MIN_ITEMS:
        reasons.append(f"only {n} labelled items (need {MIN_ITEMS})")
    if mae is None or mae > MAX_MAE:
        reasons.append(f"mean absolute error {_fmt(mae)} > {MAX_MAE}")
    if rho is None or rho < MIN_SPEARMAN:
        reasons.append(f"Spearman {_fmt(rho)} < {MIN_SPEARMAN}")
    if kappa is None or kappa < MIN_KAPPA:
        reasons.append(f"Cohen's kappa {_fmt(kappa)} < {MIN_KAPPA}")
    return Agreement(
        n=n,
        mean_absolute_error=_round(mae),
        spearman=_round(rho),
        good_agreement=_round(agree),
        cohen_kappa=_round(kappa),
        meets_bar=not reasons,
        reasons=reasons,
    )


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _fmt(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.3f}"
