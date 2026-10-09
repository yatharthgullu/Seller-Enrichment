"""
Confidence calibration.

The fusion engine's raw confidence score (source-reliability weight +
cross-document agreement) turned out to *rank* fields correctly -- higher
raw confidence reliably means higher accuracy -- but the absolute numbers
are conservative: a raw confidence of 0.55 still turns out correct ~85% of
the time. That makes a literal "accept above 0.8" threshold meaningless.

This module fits a simple monotonic step calibration (bin raw confidence,
look up each bin's empirical accuracy from the validation backtest) and
applies it to produce a `calibrated_confidence` that genuinely approximates
"P(this field is correct)". Built once from validate.py's output, applied
to every profile before export.
"""
from __future__ import annotations

from bisect import bisect_right

N_BINS = 10


class CalibrationMap:
    def __init__(self, bin_edges: list[float], bin_accuracy: list[float]):
        self.bin_edges = bin_edges  # ascending, len = N_BINS+1
        self.bin_accuracy = bin_accuracy  # len = N_BINS

    def apply(self, raw_confidence: float | None) -> float | None:
        if raw_confidence is None:
            return None
        idx = bisect_right(self.bin_edges, raw_confidence) - 1
        idx = max(0, min(idx, len(self.bin_accuracy) - 1))
        return self.bin_accuracy[idx]

    def to_dict(self) -> dict:
        return {"bin_edges": self.bin_edges, "bin_accuracy": self.bin_accuracy}

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationMap":
        return cls(d["bin_edges"], d["bin_accuracy"])


def fit_calibration(confidence_match_pairs: list[tuple[float, bool]], n_bins: int = N_BINS) -> CalibrationMap:
    """Fit from (raw_confidence, was_correct) pairs collected across every
    validated field and every seller."""
    pairs = sorted(confidence_match_pairs, key=lambda t: t[0])
    if not pairs:
        edges = [i / n_bins for i in range(n_bins + 1)]
        return CalibrationMap(edges, [0.5] * n_bins)

    edges = [i / n_bins for i in range(n_bins + 1)]
    edges[0], edges[-1] = 0.0, 1.0
    bin_accuracy = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        in_bin = [m for c, m in pairs if (lo <= c < hi) or (i == n_bins - 1 and c == hi)]
        if in_bin:
            bin_accuracy.append(round(sum(in_bin) / len(in_bin), 3))
        else:
            # empty bin: fall back to nearest non-empty neighbour, else 0.5
            bin_accuracy.append(bin_accuracy[-1] if bin_accuracy else 0.5)

    # enforce monotonic non-decreasing accuracy across bins (isotonic-style
    # cleanup) so the calibration can't tell you "more confident" means
    # "less likely correct" due to small-sample noise in a thin bin
    for i in range(1, n_bins):
        if bin_accuracy[i] < bin_accuracy[i - 1]:
            bin_accuracy[i] = bin_accuracy[i - 1]

    return CalibrationMap(edges, bin_accuracy)
