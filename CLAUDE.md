# tac-risk-gate

A tested risk gate for TAC Protocol (TAC) perpetual futures. Output is one of: **stay out / caution / clear**, always with plain-words reasons. It is NOT a price predictor.

## Rules

- Always create a feature/fix git branch before any code change. Never commit to main.
- Ask me before every commit and push.
- Never put API keys or secrets in git. Use a `.env` file and make sure `.env` is in `.gitignore`.
- Market data is read-only (public endpoints). Never write order, trading, or withdrawal code.
- No result counts as valid until it passes walk-forward backtest and paper trading.
- No look-ahead: features use only data available at that moment.
- Log every experiment and variant tried.
- Language: Python. Small modules. Tests with pytest.

## Phases

0. Data collection (Binance and Bybit public APIs, TACUSDT perpetual)
1. Literature scan
2. Features
3. Backtest and validation
4. Risk gate
5. Paper trading (8+ weeks)
6. Dashboard and alerts

## Risk defaults

- Spot first
- Leverage cap 3x
- Isolated margin only
- 1% risk per trade
- Stop-loss set at entry
