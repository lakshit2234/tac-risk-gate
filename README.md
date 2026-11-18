# tac-risk-gate

A tested risk gate for TAC Protocol (TAC) perpetual futures.

For a given moment, it outputs one of **stay out / caution / clear**, always with plain-words reasons.

**It is not a price predictor.** Its purpose is to flag when conditions are too risky to trade, not to forecast direction.

Market data is read-only (public endpoints). No order, trading, or withdrawal code. Results only count after walk-forward backtesting and paper trading.

See [CLAUDE.md](CLAUDE.md) for project rules and phases.
