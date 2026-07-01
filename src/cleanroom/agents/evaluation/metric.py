"""pass@k estimator (Chen et al., 2021 — the HumanEval/Codex metric).

For one problem you draw ``n`` samples, ``c`` of which pass. The probability that a
random subset of ``k`` of those samples contains at least one passing sample is the
unbiased estimator

    pass@k = 1 - C(n - c, k) / C(n, k)

computed below in the numerically stable product form. The overall pass@k is the
mean of this quantity across all problems.
"""


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k for a single problem.

    Args:
        n: total number of samples generated.
        c: number of samples that passed.
        k: the k in pass@k (must be <= n).
    """
    if k > n:
        raise ValueError(f"k ({k}) cannot exceed n ({n})")
    if n - c < k:
        return 1.0  # so few failures that every k-subset must contain a pass
    prod = 1.0
    for i in range(n - c + 1, n + 1):
        prod *= 1.0 - k / i
    return 1.0 - prod
