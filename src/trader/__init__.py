"""AI-assisted crypto paper-trading research system (M1 vertical slice).

Safety boundary (D-02, D-03, amended by ADR-023): paper/simulated by default. Real-money
spot trading exists only in the gated ``live`` environment (owner authorization, capital cap,
paper track record, activation). No leverage, margin, short selling, withdrawals, or
transfers exist anywhere in this package.
"""

__version__ = "0.1.0"
SAFETY_STATEMENT = (
    "Paper by default. Live spot trading only behind owner gates (ADR-023). "
    "No leverage, margin, shorting, or withdrawals."
)
