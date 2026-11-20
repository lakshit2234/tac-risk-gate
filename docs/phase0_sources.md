# Phase 0 data sources for TAC (research only)

Checked on 2026-11-20 (UTC). Every "live" result below is a real request made that day, with no API key. "Unverified" means I could not source it. Nothing here is a fetcher; no code was written. Binance comparison data is our own `data/raw/binance_TACUSDT_1m.csv` (read-only; covers 2025-07-15 10:30 to 2026-11-18 16:18 UTC).

## Summary

| # | Need | Source | Verdict | Key limit |
|---|---|---|---|---|
| 1a | Chain TVL, daily | DeFiLlama `/v2/historicalChainTvl/TAC` | **usable** | none seen; 491 daily points from 2025-07-18 |
| 1b | Protocol TVL on TAC | DeFiLlama `/protocol/{slug}` (`chainTvls.TAC`) | **partially usable** | payload is huge for big protocols (Morpho 33.6 MB, my download was cut off); small ones work (Lagoon 2.6 MB) |
| 2a | Daily price | DeFiLlama `coins.llama.fi/chart/coingecko:tac` | **usable** | full history from 2025-07-16, a few missing days; price only |
| 2b | Price + market cap + volume | CoinGecko public API `market_chart` | **partially usable** | only the last 365 days (from 2025-11-21 today, and the window moves daily); heavy throttling; 73 of 363 days disagree with Binance by more than 2% |
| 2c | Price/mcap (other) | CoinMarketCap API | **not usable yet** | needs an API key (HTTP 401 "API key missing") |
| 3 | Total / max supply | tac.build tokenomics post (official) + CoinGecko `/coins/tac` (current only) | **usable (manual)** | no history of supply; sources disagree on current numbers |
| 4a | Vesting schedule | tac.build tokenomics post (official) | **usable (manual)** | relative to TGE only, no calendar dates, several categories have no schedule |
| 4b | Unlock tracker | DeFiLlama `/emissions` | **not usable** | HTTP 402, paid plan |
| 4c | Unlock tracker | tokenomics.com, DropsTab, CoinGlass web pages | **not usable for fetching** | no API, terms not reviewed, figures disagree with each other; fine as a manual cross-check |
| 5 | Dated events | Binance support article, press, news (see section 5) | **partially usable** | 2025-10-10 and 2025-11-26 have no TAC-specific cause: unverified |

## Recommendation: build fetchers for

1. **DeFiLlama chain TVL** (`historicalChainTvl/TAC`). Free, daily, full history.
2. **DeFiLlama coin price chart** (`coingecko:tac`). Free, full history back to 2025-07-16, and closest to Binance in my check (96.5% of 491 points within 1%).
3. **CoinGecko `market_chart` (days=365), run daily and appended to a file, soon.** It is the only free source of market cap and volume. The free window is the last 365 days and rolls forward, so market cap before the first day we have saved will be lost permanently (today the window starts 2025-11-21). Treat its price as suspect (see 2b) and use it only for market cap and volume. Circulating supply history is not provided; market cap / price is a derived number, not a sourced one.
4. **Not fetchers, hand-written static files with a source URL per line:** the supply facts, the vesting schedule (official post, relative to TGE 2025-07-15) and the event list.
5. Skip for now: DeFiLlama emissions (paid), CoinMarketCap (key), the unlock websites (no API), big-protocol TVL (heavy; add only Lagoon-sized ones if wanted).

## 1. TVL (DeFiLlama)

Docs: https://api-docs.defillama.com/ (free endpoints listed at https://api-docs.defillama.com/llms-free.txt: "Free API, no authentication required"). Rate limit and terms/attribution: not stated in the docs I could read. In about 12 requests I saw no throttling and no rate-limit headers.

**Chain TVL.** `GET https://api.llama.fi/v2/historicalChainTvl/TAC`, no auth, HTTP 200. History: 491 daily points, 2025-07-18 to 2026-11-20. Docs say it excludes liquid staking and double counting. Sample: `[{"date":1752796800,"tvl":9095944},{"date":1752883200,"tvl":43839344},...,{"date":1795132800,"tvl":217080}]`. `GET /v2/chains` lists the chain as `{"name":"TAC","gecko_id":"tac","tokenSymbol":"TAC","chainId":239,"tvl":217079.87...}`, which matches the last point. Verdict: usable. Note the collapse from tens of millions to about $0.2M; I did not look for its cause (unverified).

**Protocols.** `GET /protocols` (9.7 MB) lists 16 protocols with TAC in `chains`; current TAC-chain TVL by protocol (from `chainTvls.TAC`): LayerZero V2 2,529,245; Morpho Blue 205,872; Lagoon 127,876; Euler V2 6,941; others smaller. These add up to about $2.9M while the chain figure is $0.217M; the chain figure excludes some categories, but I did not verify which, so the gap is unexplained. History: `GET /protocol/lagoon` returned 488 daily points for TAC, 2025-07-22 to 2026-11-20 (sample `{"date":1753142400,"totalLiquidityUSD":0}`). `GET /protocol/morpho-blue` is 33.6 MB and was cut off at my 150 s timeout, so it parsed as invalid JSON. Verdict: partially usable.

## 2. Price, market cap, circulating supply

**DeFiLlama prices** (`https://coins.llama.fi`, free, same terms notes as above). `GET /chart/coingecko:tac?start=1752537600&span=500&period=1d` gave 493 points, first 2025-07-16 00:00 UTC, last 2026-11-19 23:59. Sample: `{"coins":{"coingecko:tac":{"symbol":"TAC","confidence":0.99,"prices":[{"timestamp":...,"price":0.02042778},...`. Some days are missing (e.g. 2025-07-17, 07-22, 07-27, 07-31, 2026-04-30; and 2026-07-07 has no point). Price only: no market cap, no supply. `GET /prices/current/coingecko:tac` returned 0.00127957. Verdict: usable.

**CoinGecko public API** (`https://api.coingecko.com/api/v3`, no key). `/coins/tac` works (id `tac`). `/coins/tac/market_chart?vs_currency=usd&days=365&interval=daily` returned 366 points for prices, market_caps and total_volumes, 2025-11-21 to 2026-11-20; sample price `[1763683200000, 0.004091792873047377]`, market cap `[1763683200000, 10673533.63]`. `days=max` is refused: HTTP 401, error 10012 "Public API users are limited to querying historical data within the past 365 days". A burst of 3 requests within seconds got HTTP 429 "Throttled" on the third. The docs pages I could fetch gave no numbers for rate limits or attribution, so those are unverified; the Demo plan (free, needs a key signup) was not used. Verdict: partially usable.

Sanity check against our Binance 1m klines (CoinGecko daily value stamped 00:00 UTC vs Binance 1m open at 00:00 UTC, 363 matching days): median absolute difference 0.35%; 79% of days within 1%; but **73 of 363 days differ by more than 2%**, in runs between 2026-01-10 and 2026-08-23, up to +93%. Examples: 2026-02-12 CoinGecko 0.007082 vs Binance 0.004292 (+65%); 2026-03-19 0.006903 vs 0.004009 (+72%). The cause is unverified. On normal days they agree (2026-11-17: 0.001187 vs 0.001186, +0.12%).

DeFiLlama against Binance (DeFiLlama points, mostly about 23:59 UTC, against the Binance 1m close of the same minute, 491 points): median absolute difference 0.31%; 96.5% within 1%; one point above 5% (2026-08-22 23:51 UTC, 37.9%, the day the August exploit was disclosed). Example 2025-11-26 23:59: 0.006178 vs 0.006211 (-0.53%).

Current supply fields from CoinGecko `/coins/tac` (2026-11-20): circulating 6,485,581,286; total 10,030,078,763; max supply null (`max_supply_infinite: true`). No supply history is offered on the free tier.

**CoinMarketCap**: `https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol=TAC` returned HTTP 401 `{"error_message":"API key missing."}`. Not usable yet.

## 3. Total and max supply

- Official (https://tac.build/blog/introducing-tac-token-utility-and-tokenomics-of-the-tac-protocol-token, dated 2025-07-14, updated 2025-07-15): total supply 10 billion; max annual inflation 5% (effective 2.1%, the part that raises circulating supply); circulating at TGE 18%. A max supply is not stated beyond the 10B total.
- CoinGecko today: total 10,030,078,763, no max. DropsTab: total 10.13B (seen on its vesting page). Both are above the official 10B; the reason (inflation or definitions) is **unverified**.
- Circulating supply today disagrees widely: CoinGecko 6.49B; tokenomics.com 4.83B (stated as a July 2026 snapshot); CoinGlass "unlocked" 3.02B; DropsTab 3.12B unlocked. Which is right is **unverified**; use none as a feature without checking.

## 4. Vesting and unlocks

**Official** (same tac.build post; all schedules relative to TGE; the post does not state the TGE date, but Binance and the mainnet press release give 2025-07-15):

| Category | % of supply | Vesting as stated |
|---|---|---|
| Investors and advisors | 20% (16.6% investors, 3.4% advisors) | 12-month cliff from TGE, then linear over 24 months |
| Early contributors (team) | 22.1% | locked 1 year from TGE, then linear over 2 to 3 years |
| Foundation and reserve | 14.8% | unlocked at genesis |
| DAO treasury | 12% | mostly locked, vested over about 36 months, 5% unlocked at TGE |
| Growth programs | 10.0% | unlocked, held by the foundation at TGE; 6% pre-allocated to long-term DeFi incentives |
| Liquidity management | 3% | unlocked at TGE |
| Launch marketing and rewards | 4.4% | CEX listings 2.80%, airdrops 1.42%, other 0.2%; timing not stated |
| Mid-term marketing and rewards | 4.6% | schedule not stated |
| Pre-mainnet liquidity (TAC Summoning) | 5.1% | 3.3% at TGE, remaining 1.75% over about 1.5 months |
| Validator bootstrapping | 3.0% | strict lock-up, schedule not stated |
| Infrastructure partnerships | 1% | unlocked at TGE |

Airdrop: 1.42% of supply (down from "up to 3%"; the other 1.58% went to the DAO treasury). Calendar dates are not given; the cliff end for investors and advisors (about 2026-07-15) is my arithmetic from TGE + 12 months, not a stated date.

**DeFiLlama unlocks**: `GET https://api.llama.fi/emissions` returned HTTP 402 "Upgrade to the paid API plan". Not usable. (`pro-api.llama.fi` answers "API Key is wrong".)

**Free trackers (web pages, no API; I did not review their terms and did not scrape).** tokenomics.com (https://app.tokenomics.com/tokenomics/tac/unlocks) shows 48 monthly unlocks on the 15th, 2025-07-15 to 2029-06-15, next Dec 15, 2026 at 3.30% of market cap, recipients Insiders 46%, Private investors 42.1%, Foundation 11.8% (page states "As of November 2026"). DropsTab (https://dropstab.com/coins/tac/vesting) and CoinGlass show a next unlock of about 99.4M TAC around 2026-11-15, split Advisors 13.6M, DAO treasury 19.43M, Seed 66.4M. These disagree on the next date and amount, and DropsTab warns its data may be inexact, so the exact schedule is **unverified**. Verdict: use only to cross-check the official post by hand.

## 5. Events for the price timeline

For each requested day, Binance daily figures are from our klines (UTC day).

**2025-10-10.** TAC on Binance: open 0.00594, low 0.00103, close 0.00427 (-28%), intraday range 498%, volume 5.2M USDT. Market-wide context (sourced): the Oct 10 2025 crypto crash, over $19B liquidated, triggered by a tariff announcement, with Binance-specific problems (https://www.coingecko.com/learn/october-10-crypto-crash-explained). That article does not mention TAC. A TAC-specific cause: **unverified**. The 1m wick to 0.00103 is consistent with the market-wide event but I found no TAC source.

**2025-11-26.** TAC on Binance: open 0.00432, high 0.01690, close 0.00621 (+44%), range 298%, quote volume 567.5M USDT (about 475 times the previous day's 1.19M). Cause: **unverified**. My searches found no source for this day. (A search snippet mentioned a Tapbit blog post dating a rise to 2025-11-27; it is a promotional post I did not open, so I do not rely on it.)

**2026-07-07.** TAC on Binance: open 0.03232, high 0.05456, low 0.00402, close 0.00451 (-86%), quote volume 329M USDT. Sources: Cryptonomist, published 2026-07-07, says TAC lost more than 90% in 15 minutes on Binance Alpha, bottoming near 0.0063, with no official explanation yet (https://en.cryptonomist.ch/2026/07/07/tac-token-price-drop/). Mitrade, 2026-08-25, says the token dropped about 82% to about 0.0056 on July 7 "with no explanation" (https://www.mitrade.com/insights/news/live-news/article-3-2026902-20260825). Search snippets (Cryptorank, Mitrade 2026-07-09, pages I could not open or only saw as snippets) say the team blamed a liquidation cascade that began with a large perpetual sell order in thin liquidity, and on-chain analysts doubted that. The cause is **unverified**: the team's explanation is disputed. Reported lows (0.0045 to 0.0063) differ from the Binance perp 1m low (0.00402); I did not resolve this.

**Key dated events since launch**

| Date (UTC) | Event | Source |
|---|---|---|
| 2025-07-14 | Binance announces TAC on Alpha and Futures | https://www.binance.com/en/support/articles/91588d0f0301485385461a3b933c7b1b |
| 2025-07-15 | Mainnet and TAC token live; Binance Alpha opens 10:00, TACUSDT perpetual opens 10:30 (50x max, 4-hourly funding, per the article; our first kline is 10:30, matching) | same Binance article; https://decrypt.co/330189 (Chainwire release dated July 15, 2025) |
| 2025-07-15 to 07-16 | Binance Alpha airdrop claim window 10:00 to 10:00 UTC | Binance article above |
| 2025-07-16 | Summoning "Phase 1" airdrop claims open (one guide; partially verified) | https://bingx.com/en/learn/article/how-to-claim-tac-protocol-tac-airdrop-with-a-ton-wallet (seen as a snippet) |
| 2025-07-15 | TAC perpetual also listed on BloFin and MEXC futures (titles in search results only; dates for BloFin unverified) | https://www.mexc.com/he-IL/support/articles/17827791525983 |
| 2026-05-11 or 05-12 | Cross-chain bridge exploit on the TON side, about $2.8M (USDT, BLUM, tsTON); later called white-hat, about 90% recovered, bridge reopened June 10. Sources disagree on the day (most say May 12) | https://www.mitrade.com/insights/news/live-news/article-3-2026902-20260825 (fetched); details from search snippets (Cryptopolitan, CoinStats, CoinMarketCap community) |
| 2026-06-29 and 06-30 | Binance perp daily +172% on 06-29 (our klines); CoinGecko all-time high 0.067146 on 2026-06-30. One article ties it to a "v1.6.0 mainnet upgrade scheduled June 30" and a 163M TAC cross-chain transfer, but it is undated, its own tables are inconsistent, and I rate it unreliable | https://intellectia.ai/news/crypto/tac-protocol-price-surges-16673-amid-major-token-transfer (unreliable) |
| 2026-07-07 | Crash (above) | above |
| 2026-07-15 | End of the 12-month cliff for investors and advisors (my arithmetic: TGE + 12 months, not a stated date) | official tokenomics post |
| 2026-08-22 | Exploit on the Cosmos EVM side, chain halted at block 24,671,475 per TAC; the team says only native TAC was taken. The article gives no year in its text; its address date is 2026-08-25, and CoinGecko's all-time low is 2026-08-23 | https://www.mitrade.com/insights/news/live-news/article-3-2026902-20260825 |
| 2026-08-27 | A "price protection mechanism" for the TACUSDT perpetual (single snippet): **unverified** | TechFlow snippet only |
| monthly, the 15th | Token unlock events (see section 4, dates and sizes disagree between trackers) | section 4 |

Not found: any dated "major exchange spot listing" other than Binance Alpha and the perpetuals above (**unverified**).

## What I did not verify

CoinGecko and DeFiLlama rate limits and terms of use (docs gave no numbers; I only observed behaviour); the cause of CoinGecko's multi-day price gaps; the reason total supply is above 10B; why protocol TVL exceeds chain TVL; causes of the 2025-10-10 and 2025-11-26 moves; the unlock tracker terms.

## Decisions (approved)

- **Fetcher build order:**
  1. CoinGecko `market_chart`: raw data, daily append, every row stored with `fetched_at`. It is never used as a price. Days where it mismatches Binance are excluded.
  2. DeFiLlama chain TVL.
  3. DeFiLlama coin price.
- **Static files, hand-written:** supply, vesting and events, with a source URL on every line.
- **Skipped:** DeFiLlama emissions, CoinMarketCap, the unlock websites, and big-protocol TVL.
- **Known limitation:** unlock timing and circulating supply history are not obtainable for free, so the risk gate cannot rely on them.
- **Event labels:** defined by what the data shows. The cause is written "unverified" unless it is sourced.

## Errata and updates (2026-11-20)

1. **DeFiLlama price had no missing days.** The earlier claim that the price series had missing days (2025-07-17, 07-22, 07-27, 07-31, 2026-04-30 and 2026-07-07) was wrong. There are 0 missing days in 493 points. My floor-based day check was the error: price timestamps sit seconds either side of a UTC midnight, so they must be assigned to the nearest midnight.
2. **Circulating supply.**
   - Binance `openInterestHist` returns `CMCCirculatingSupply` as the 4th field. Its history is only about 30 days, and the recorder stores it going forward.
   - CoinGecko market_cap divided by price equals the same CMC supply. It is not independent information, but it is a usable derived circulating-supply history, and it is robust to CoinGecko's price errors.
   - The earlier limitation "circulating supply history not obtainable" is softened accordingly.
   - Unlock timing is still not obtainable for free.
   - Supply steps in the derived series can be labelled "supply step" events, with cause "unverified".
3. **Look-ahead rule.** CoinGecko's daily point for 2026-11-19 00:00 UTC already reflected a supply update that Binance only published at 02:35 UTC that day (inference, not verified). All daily external rows (CoinGecko, DeFiLlama TVL, DeFiLlama price) must therefore be treated as known at timestamp + 24 hours, never earlier.
