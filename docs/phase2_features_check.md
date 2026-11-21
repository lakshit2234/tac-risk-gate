# Phase 2 price-based features check

Generated 2026-11-21 (UTC) by `python -m tacgate.phase2.features_klines`. Read-only. Features only: no label is read, nothing is compared with a label, nothing is fitted. Source: Binance TACUSDT perpetual 1m last-price klines (2025-07-15 10:30 to 2026-11-18 16:18 UTC) and Bybit TACUSDT perpetual 1m klines, through `loaders.load_klines`.

## 1. Rules

- Decision times: every 5 minutes, the same grid as the labels. A kline is known at its open + 60 seconds, so at decision time t the candle that closed at t (opened at t - 60 s) is the newest one used. The candle that opens at t is never used.
- **Fixed windows: 15 minutes, 1 hour, 4 hours, 24 hours. Volume baseline: 7 days.** They were fixed in advance by the user on 2026-11-21 (proposed by Claude, approved by the user) and are one constant (`WINDOWS`) in the code. Nothing else is a parameter.
- A missing minute inside the inputs of a feature makes that feature NaN. Not enough history yet (warm-up) is NaN. Nothing is filled, imputed or interpolated.

## 2. The features

| Feature | Columns | Definition (w = the window) |
|---|---|---|
| ret | `ret_15m`, `ret_1h`, `ret_4h`, `ret_24h` | close_t / close_(t-w) - 1 (the close of the candle that closed at t - w) |
| rv | `rv_15m`, `rv_1h`, `rv_4h`, `rv_24h` | standard deviation (n - 1) of the w one-minute log returns in the window |
| drawdown | `drawdown_15m`, `drawdown_1h`, `drawdown_4h`, `drawdown_24h` | close_t / (highest 1m high in the window) - 1; never above 0 |
| runup | `runup_15m`, `runup_1h`, `runup_4h`, `runup_24h` | close_t / (lowest 1m low in the window) - 1; never below 0 |
| range | `range_15m`, `range_1h`, `range_4h`, `range_24h` | (highest high - lowest low in the window) / close_t |
| taker_buy_share | `taker_buy_share_15m`, `taker_buy_share_1h`, `taker_buy_share_4h`, `taker_buy_share_24h` | taker buy base volume / base volume over the window, from the klines only; between 0 and 1; NaN if the window has no volume |
| volume_ratio | `volume_ratio_15m`, `volume_ratio_1h`, `volume_ratio_4h`, `volume_ratio_24h` | base volume in the window / mean base volume of the non-overlapping windows of the same length in the 7 days before it |
| bybit_gap | `bybit_gap` | (binance close_t - bybit close_t) / binance close_t, both candles opened at t - 60 s |
| bybit_gap_abs_max_1h | `bybit_gap_abs_max_1h` | the largest absolute gap over the 60 candles of the last hour (NaN if any of them is missing) |

A window of w minutes is the w candles opened in [t - w, t). `ret` and `rv` need one more close (w + 1 closes), because they start from the close of the candle before the window. The window labels are 15m, 1h, 4h and 24h.

## 3. Candle gaps (days that cause NaN)

- Binance 1m klines: 707,389 candles, **0 gaps** (0 missing minutes).
- Bybit 1m klines: 707,404 candles, **0 gaps** (0 missing minutes). Bybit starts 2025-07-15 11:00 UTC and ends 2026-11-18 17:03 UTC; candles after the last Binance candle are not used.

So no candle-gap day causes any NaN. Every NaN below is warm-up (the first window, the first 7 days for the volume ratio, and the first 30 minutes of Bybit data) or a window with no volume at all.

Bybit candles with zero volume: 123,561 of 707,404 (17.5%); Binance: 5,814 of 707,389. They are real rows (not missing), so they are used as they are; the Bybit close of a zero-volume candle may be stale. See OPEN below.

## 4. NaN counts

All 141,477 decision times, of which 109,602 are in the development period (up to 2026-07-31 00:00 UTC). The NaN rows are the warm-up at the start of the data.

| Feature | NaN, all decision times | NaN, development period |
|---|---|---|
| `ret_15m` | 3 | 3 |
| `ret_1h` | 12 | 12 |
| `ret_4h` | 48 | 48 |
| `ret_24h` | 288 | 288 |
| `rv_15m` | 3 | 3 |
| `rv_1h` | 12 | 12 |
| `rv_4h` | 48 | 48 |
| `rv_24h` | 288 | 288 |
| `drawdown_15m` | 2 | 2 |
| `drawdown_1h` | 11 | 11 |
| `drawdown_4h` | 47 | 47 |
| `drawdown_24h` | 287 | 287 |
| `runup_15m` | 2 | 2 |
| `runup_1h` | 11 | 11 |
| `runup_4h` | 47 | 47 |
| `runup_24h` | 287 | 287 |
| `range_15m` | 2 | 2 |
| `range_1h` | 11 | 11 |
| `range_4h` | 47 | 47 |
| `range_24h` | 287 | 287 |
| `taker_buy_share_15m` | 3 | 3 |
| `taker_buy_share_1h` | 11 | 11 |
| `taker_buy_share_4h` | 47 | 47 |
| `taker_buy_share_24h` | 287 | 287 |
| `volume_ratio_15m` | 2,018 | 2,018 |
| `volume_ratio_1h` | 2,027 | 2,027 |
| `volume_ratio_4h` | 2,063 | 2,063 |
| `volume_ratio_24h` | 2,303 | 2,303 |
| `bybit_gap` | 6 | 6 |
| `bybit_gap_abs_max_1h` | 17 | 17 |

## 5. Summary numbers (development period only: decision times up to 2026-07-31 00:00 UTC)

Minimum, median and maximum of the values that are not NaN. Nothing from the holdout is summarised.

| Feature | Minimum | Median | Maximum |
|---|---|---|---|
| `ret_15m` | -0.8312 | 0 | 1.0459 |
| `ret_1h` | -0.8867 | -0.000228 | 2.9908 |
| `ret_4h` | -0.9104 | -0.0008525 | 2.8899 |
| `ret_24h` | -0.9424 | -0.0057 | 3.3394 |
| `rv_15m` | 0 | 0.0015 | 0.2856 |
| `rv_1h` | 0.0002028 | 0.0017 | 0.1525 |
| `rv_4h` | 0.0003711 | 0.0018 | 0.0777 |
| `rv_24h` | 0.00047 | 0.0019 | 0.0318 |
| `drawdown_15m` | -0.8337 | -0.0039 | 0 |
| `drawdown_1h` | -0.8952 | -0.0081 | 0 |
| `drawdown_4h` | -0.9151 | -0.0169 | 0 |
| `drawdown_24h` | -0.9466 | -0.0458 | 0 |
| `runup_15m` | 0 | 0.0037 | 1.2330 |
| `runup_1h` | 0 | 0.0076 | 3.7087 |
| `runup_4h` | 0 | 0.0157 | 3.7087 |
| `runup_24h` | 0 | 0.0402 | 3.8350 |
| `range_15m` | 0 | 0.0086 | 5.2143 |
| `range_1h` | 0.0013 | 0.0180 | 8.5704 |
| `range_4h` | 0.0037 | 0.0371 | 10.8048 |
| `range_24h` | 0.0126 | 0.0972 | 17.7779 |
| `taker_buy_share_15m` | 0.0271 | 0.4925 | 0.9711 |
| `taker_buy_share_1h` | 0.1324 | 0.4896 | 0.8834 |
| `taker_buy_share_4h` | 0.2808 | 0.4868 | 0.7172 |
| `taker_buy_share_24h` | 0.3945 | 0.4859 | 0.5681 |
| `volume_ratio_15m` | 0 | 0.4229 | 439.0932 |
| `volume_ratio_1h` | 0.0262 | 0.5010 | 608.9741 |
| `volume_ratio_4h` | 0.0447 | 0.5789 | 762.9572 |
| `volume_ratio_24h` | 0.0572 | 0.6700 | 201.4835 |
| `bybit_gap` | -0.0991 | 0.0009132 | 0.1063 |
| `bybit_gap_abs_max_1h` | 0.0005778 | 0.0034 | 0.3743 |

Bounds on the development period: taker_buy_share_15m between 0 and 1: holds; drawdown_15m at most 0: holds; runup_15m at least 0: holds; taker_buy_share_1h between 0 and 1: holds; drawdown_1h at most 0: holds; runup_1h at least 0: holds; taker_buy_share_4h between 0 and 1: holds; drawdown_4h at most 0: holds; runup_4h at least 0: holds; taker_buy_share_24h between 0 and 1: holds; drawdown_24h at most 0: holds; runup_24h at least 0: holds.

## Decisions

**Decided by the user:**

- The windows (15 min, 1 h, 4 h, 24 h) and the 7 day volume baseline were fixed in advance by the user on 2026-11-21 (proposed by Claude, approved by the user). They are constants in `features_klines.py`, not parameters.
- No feature is compared with any label in this task: no correlation, AUC or hit rate. Summary numbers use the development period only.

**OPEN (not decided):**

- Whether each feature should later be built from the mark price instead of the last price (mark klines are not downloaded yet).
- How to treat `bybit_gap` when Bybit data has gaps. Today a missing Bybit minute makes it NaN; a Bybit candle with zero volume is used as it is (its close is the last traded price, possibly stale).
- Whether a volume baseline with a missing minute should stay NaN for 7 days (today's strict rule) or skip only the affected baseline windows. It does not matter on the current data (no missing minute), but it will after the first gap.

