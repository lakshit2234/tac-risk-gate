# Phase 1 literature scan: risk in leveraged positions on thin perpetual futures

The candidate Stage A rules in this scan are hypotheses to test on our data, not rules to adopt, and every variant tried must be counted and reported.

Written 2026-11-20. Scope: what is known about risk when holding a leveraged perpetual-futures position on a small, thin coin, and which simple signals have real evidence. This is for a risk gate (stay out / caution / clear), not price prediction.

How to read this. Every source below was opened by Claude Code during this scan (full text extracted and skimmed, or abstract or landing page only, as marked). Nothing is cited from memory. Findings are paraphrased. Evidence strength: **peer-reviewed**, **working paper / preprint** (not peer-reviewed), **industry** (blog, vendor, exchange, market-maker or news report), **other**. Several sources are 2026 preprints by single authors; I could not check their data. "No good evidence found" is used where it applies.

## 1. Liquidation cascades and leverage in perpetuals

- **Liquidation, Leverage and Optimal Margin in Bitcoin Futures Markets**. Cheng, Deng, Wang, Yu (2021). arXiv 2102.04591 (https://arxiv.org/abs/2102.04591). *Read:* full text extracted, abstract and introduction read. *Strength:* preprint (no journal seen). *Finding:* on BitMEX perpetual BTC futures, forced liquidations were large (about 3.5% of outstanding long and 1.9% of short positions per day), liquidated traders had used about 60x leverage on average, and margins sized from extreme-value tails need to be much higher than margins sized from a normal distribution. *Limit:* BTC on one venue around 2020; about margin design, not warning signals; says nothing about thin coins.
- **Where does the criticality live? Early-warning signals are event-heterogeneous across seven crypto-perpetual liquidation cascades**. Garcia Seuma (2026). arXiv 2607.27070 (https://arxiv.org/abs/2607.27070). *Read:* full text extracted, abstract, introduction and limitations read. *Strength:* preprint, single author. *Finding:* across seven BTC cascades (2022 to 2025, including 2025-10-10), using minute prices and Binance 5-minute open interest, long/short and taker data, no variable gave a warning in every event; a price early-warning pattern appeared before five of seven but not before the two sudden tariff-news shocks; the one regularity that survived a placebo test was a shrinking of taker order-flow variance before cascades, which the author calls a population-level precursor, not an alarm for any single event. *Limit:* seven events, one venue, moderate effects, leverage variables are proxies for liquidations (not observed); BTC only.
- **Measuring the engine of a liquidation cascade**. Garcia Seuma (2026). arXiv 2608.03616 (https://arxiv.org/abs/2608.03616). *Read:* full text extracted, abstract and introduction read. *Strength:* preprint, same author. *Finding:* the 2025-10-10 cascade was abrupt, not a slow build-up; in the cascade price impact rose several-fold and open interest fell by 25 to 70%; the author finds that none of the single "pre-state" leverage or fragility measures grades how severe a cascade will be. *Limit:* seven events, mostly BTC, a transparent venue (Hyperliquid) for the mechanism work.
- **Autodeleveraging: Impossibilities and Optimization**. Chitra (2025, revised 2026). arXiv 2512.01112 (https://arxiv.org/abs/2512.01112). *Read:* abstract only. *Strength:* preprint. *Finding:* models the last-resort loss-sharing mechanism of perpetual venues; reports that on 2025-10-10 Hyperliquid's version took more profit from winning traders than needed. *Limit:* about exchange design, not trader risk signals.
- **Small, thin contracts:** no good evidence found. Search results mentioned manipulation incidents on thin perpetuals (for example a Hyperliquid delisting), but those were secondary write-ups I did not open, so they are not used.

## 2. Funding rate

- **Fundamentals of Perpetual Futures**. He, Manela, Ross, von Wachter (2022, revised 2026). arXiv 2212.06888 (https://arxiv.org/abs/2212.06888). *Read:* abstract only. *Strength:* preprint. *Finding:* derives no-arbitrage prices for perpetuals; observed prices deviate from them more in crypto than in traditional currency markets, the deviations move together across coins and shrink over time. *Limit:* about pricing and arbitrage, not crash or return prediction; abstract only.
- **Crypto carry**. Schmeling, Schrimpf, Todorov (2023). BIS Working Paper 1087 (https://www.bis.org/publ/work1087.htm). *Read:* landing page and abstract only. *Strength:* working paper. *Finding:* the gap between futures and spot (carry) can reach about 60% a year and averages above 10%; the authors attribute it to leveraged trend-chasing demand and limited arbitrage capital; the page states that high carry tends to precede price crashes and that arbitrage positions can be forced out by margin spikes in drawdowns. *Limit:* BTC and ETH; carry (the futures-spot gap) is related to funding but is not the same thing; abstract only.
- **Extreme Perpetual Futures Funding and Subsequent Bitcoin Returns: Intraday Evidence from Binance**. Memon, Anklesaria-Dalal, Mishra (2026). Advanced International Journal of Multidisciplinary Research 4(4) (https://www.aijmr.com/papers/2026/4/1493.pdf). *Read:* full text extracted, abstract and limitations read. *Strength:* other (a multidisciplinary journal of unclear standing; treat as a preprint). *Finding:* when Binance BTC funding was in the lowest decile of its own previous 180 days, the next 24 hours of BTC returns averaged about +0.5%; extreme positive funding showed no comparable effect; some tests at some horizons lose significance after multiple-testing adjustment. *Limit:* BTC and one venue only, the result is about returns after extreme negative funding, not about crashes.
- **Does funding predict crashes?** No good evidence found. What I opened supports funding as a carry cost and as a conditioning variable relative to its own history; none of it tests funding as a crash warning on small coins. A fourth paper (arXiv 2601.06084, on funding and 4-hour context) was opened and dropped: it is conceptual, with no data test.

## 3. Open interest and long/short ratios

- The two Garcia Seuma papers (section 1) are the only tested evidence I opened. Open interest falls during and after cascades (about -25% across the 2025-10-10 event in BTC), which makes it a consequence, not a leading signal. Taker order-flow variance compression is the only precursor that survived a placebo test, and only as a population-level pattern.
- **Inferring Leveraged Positioning from Price and Open Interest**. Glassnode Research (Theissen, 2025). https://research.glassnode.com/leverage-position-openings-and-closures/. *Read:* web page. *Strength:* industry. *Finding:* proposes reading price and open interest trends together to classify long and short openings and closures. *Limit:* no backtest, no out-of-sample test, no statistics; thresholds are described as arbitrary; the author notes it lags intraday moves.
- **Long/short account ratios as a crash signal:** no good evidence found. I saw vendor and news posts in search results but did not open them; a figure I saw quoted (an odds ratio for open-interest changes before extreme declines) could not be traced to a paper, so it is not used.

## 4. Volatility forecasting

- **Comparing volatility forecasting models for cryptocurrencies and the stock market** (in Russian; HSE Economic Journal 27(1), 2023). Aganin, Manevich, Peresetsky, Pogorelova. https://ej.hse.ru/article/view/29162. *Read:* abstract page only. *Strength:* peer-reviewed. *Finding:* for next-day realized volatility of Bitcoin (2018 to 2021, 5-minute data, rolling 399-day windows), HAR-RV models forecast better than GARCH-type models; the best relative error was still about 29.5%. *Limit:* BTC and one equity future, daily horizon, abstract only; it does not test thin coins or crash detection.
- Other comparisons appeared in search results (for example a 2022 paper on GARCH versus HAR models for Bitcoin) but were not opened, so they are not used. Evidence on how hard realized volatility is to beat is therefore thin: I can only say that a HAR-type baseline on realized volatility beat GARCH in the one study I opened, and that errors remain large.

## 5. Token unlocks and vesting

- **From Locked to Liquidity: What 16,000+ Token Unlocks Teach Us**. Keyrock (undated, page footer 2026). https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/. *Read:* full web page. *Strength:* industry (a market maker with a commercial interest). *Finding:* about 40 tokens, daily prices 30 days before and after each unlock, normalised by ETH; reports that most unlocks coincide with negative price pressure, that pressure often starts about 30 days before and fades about 14 days after, that team unlocks are the worst (about -25%) and ecosystem unlocks the mildest. *Limit:* period and token list not given, no significance tests, the method is only loosely described, how the headline numbers were computed is not stated.
- Peer-reviewed measured impact of token unlocks: no good evidence found. Search results returned only industry posts.

## 6. Exploits and hacks

- **The Price of Processing: Information Frictions and Market Efficiency in DeFi**. Azar, Olivas, Sinha (2025). Federal Reserve Bank of New York Staff Report 1153 (https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1153.pdf). *Read:* full text extracted, abstract and sample description read. *Strength:* working paper (staff report, preliminary). *Finding:* a minute-level event study of 49 DeFi protocol hacks; about 36% of the total 24-hour price fall happens before the public announcement, between the on-chain hack and the social-media disclosure. *Limit:* DeFi protocol governance tokens, 49 events; says little about a layer-1 token like TAC.
- **The Impact of Blockchain Security Breaches on Crypto Token Valuation**. Li, Zhou, Cavusoglu (2025). HICSS-58 (https://aisel.aisnet.org/hicss-58/in/cybercrime/2/). *Read:* abstract only. *Strength:* peer-reviewed conference paper. *Finding:* token prices fall significantly on the breach day and over a three-day window; projects that mainly provide financial services fall more. *Limit:* sample size is not in the abstract; abstract only.
- **The Economic Impact of DeFi Crime Events on DAOs**. Kitzler, Paquet-Clouston, Haslhofer (2025). arXiv 2510.00669 (https://arxiv.org/abs/2510.00669). *Read:* abstract only. *Strength:* preprint. *Finding:* of 22 events (2020 to 2022), about 55% showed a significant negative effect on the governance token, averaging roughly 14%. *Limit:* 22 events, DAO tokens, abstract only.
- **Hacked tokens' price after a hack**. Immunefi report as summarised by Cointelegraph (2026-03-19). https://cointelegraph.com/news/hacked-crypto-tokens-drop-61-on-average-and-rarely-recover-security-report-says-embargo-thursday. *Read:* the news article (not the report). *Strength:* industry. *Finding:* across 82 hacked tokens the median fall within six months was 61%. *Limit:* no method, no market-wide baseline, the article mixes "average" and "median"; I did not see the report itself.

Taken together: tokens tend to fall around hacks, the size varies widely by study, and a good part of the fall can come before the public notice. This matches what we saw on 2026-08-22.

## 7. Order book depth, spread and slippage

- **Slippage-at-Risk (SaR)**. Sepper (2026). arXiv 2603.09164 (https://arxiv.org/abs/2603.09164). *Read:* full text extracted, abstract, validation section and limitations read. *Strength:* preprint, single industry author. *Finding:* proposes measuring liquidation-execution risk from the current order book; on Hyperliquid data including 2025-10-10, the measure's correlation with later deficits peaks at the same time and stays positive for 12 to 24 hours of lead. *Limit:* correlation-based validation on rolling windows, one venue, one main stress event; the author lists data, calibration and manipulation (inflating depth) as limits; I could not check the data.
- **Slippage-at-Risk Across Exchanges and Market Regimes**. Ruan (2026). Working paper, Cornell (https://qihongruan.github.io/sar-research/). *Read:* the paper's web page. *Strength:* working paper. *Finding:* Kaiko top-10-level snapshots from five venues over eight periods (2020 to 2023, four of them stress events): slippage falls roughly in proportion to depth, and the choice of exchange matters more than the timing. *Limit:* top 10 levels only, one snapshot a minute, the depth-slippage fit rests on a scatter plot, shorter coverage for some venues.
- **Two-Regime Liquidity Recovery After a Perpetual Futures Liquidation Cascade**. Lim (2026). Journal of FinTech and Digital Assets 1(2) (https://journals.lincoln.ac.nz/index.php/JFDA/article/download/1395/965/3881). *Read:* abstract and first page only. *Strength:* journal article by a single independent researcher in a new journal. *Finding:* on Hyperliquid (BTC, ETH, SOL, XRP, DOGE) after 2025-10-10 quoted spreads returned to about 1.1 to 1.2 times their pre-event level within 23 days, but depth near the quote stayed at 66 to 79% of its earlier level for four of five contracts; spread alone understates impaired liquidity. *Limit:* major coins on a decentralised venue, one event.
- **Binance USDE/USDT order book on 2025-10-10**. Cointelegraph Research (2025-10-15), using Rena Labs data. https://cointelegraph.com/research/exclusively-obtained-orderbook-data-reveals-details-about-usde-crash. *Read:* article. *Strength:* industry. *Finding:* on one Binance pair, liquidity fell about 74% in roughly 15 minutes and quoted spreads reached about 22%. *Limit:* one pair, one event, no method for the data vendor.
- Depth and spread for thin perpetuals on a centralised venue: no good evidence found beyond the above (none of it is about thin coins).

## 8. Backtest overfitting and validation with few events

- **The Probability of Backtest Overfitting**. Bailey, Borwein, López de Prado, Zhu (preprint Nov 2014; later published in the Journal of Computational Finance per search results). Author copy at https://carmamaths.org/jon/backtest2.pdf. *Read:* full text extracted, abstract and the hold-out discussion read. *Strength:* peer-reviewed (the preprint thanks referees; I read the preprint). *Finding:* a simple hold-out period is unreliable for judging an investment backtest, especially in small samples; the authors give a method (combinatorially symmetric cross-validation) to estimate how likely it is that the best of many tried configurations is overfit. *Limit:* built for choosing among many strategy variants with enough history; gives no power figure for our case.
- **The Deflated Sharpe Ratio**. Bailey, López de Prado (2014). Journal of Portfolio Management (forthcoming at the time). Author copy at https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf. *Read:* abstract only. *Strength:* peer-reviewed. *Finding:* a reported Sharpe ratio is inflated when many trials were run and when returns are not normal; the deflated version adjusts for both. *Limit:* abstract only; it is about Sharpe ratios of strategies, and a stay-out gate may not be evaluated that way.
- **Interpretable Hypothesis-Driven Trading: A Rigorous Walk-Forward Validation Framework**. Deep, Deep, Lamptey (2025). arXiv 2512.12924 (https://arxiv.org/abs/2512.12924). *Read:* abstract only. *Strength:* preprint. *Finding:* an example of an honest walk-forward test on 100 US stocks over 2015 to 2024: weak results, strongly regime dependent, and not statistically significant overall. *Limit:* different asset class; abstract only.
- **Purged and embargoed cross-validation, combinatorial purged cross-validation:** no good evidence opened. The pages I found were secondary (a library page, blogs), and the encyclopedia page was not reachable; I will not describe the method from them or cite the original book from memory.

## 9. Price differences between venues or aggregators during stress

- **Trading and arbitrage in cryptocurrency markets**. Makarov, Schoar (2020). Journal of Financial Economics 135(2) (https://researchonline.lse.ac.uk/id/eprint/100409). *Read:* abstract page only. *Strength:* peer-reviewed. *Finding:* large, recurring price gaps across exchanges, much larger across countries than within one country, widening when bitcoin rises sharply. *Limit:* mostly cross-country gaps for BTC and large coins; sample period not stated on the page I saw.
- **Building Trust Takes Time: Limits to Arbitrage for Blockchain-Based Assets**. Hautsch, Scheuch, Voigt (2018, revised 2023). arXiv 1812.00595 (https://arxiv.org/abs/1812.00595). *Read:* abstract only. *Strength:* preprint. *Finding:* large cross-exchange gaps appear when settlement is slow and arbitrage is costly. *Limit:* Bitcoin and large venues, abstract only.
- **October 10 explained**. CoinGecko Learn (https://www.coingecko.com/learn/october-10-crypto-crash-explained), and the Cointelegraph Research piece above. *Read:* both articles. *Strength:* industry. *Finding:* on 2025-10-10 some assets (USDe and others) traded far from their pegs on Binance only, while other venues stayed near par; reported liquidation totals vary by source. *Limit:* secondary reporting, Binance-local dislocations in stable or staked assets, not small tokens. A Kaiko note on the same topic could not be opened.
- **Aggregator prices (CoinGecko, DeFiLlama) on a thin token after a shock:** no good evidence found. Our own divergence report (docs/aug_2026_divergence_report.md) is the only evidence we have.

## A. Candidate Stage A rules

Rules with at least some support, in plain words. No thresholds or weights are proposed here; those must come from our own walk-forward work.

| # | Candidate rule | Support and level | Topic |
|---|---|---|---|
| 1 | After a liquidation cascade or a sharp loss of book depth, stay out or use caution until depth recovers; do not wait only for the spread to normalise. | Depth stayed impaired weeks after a cascade while spreads recovered (journal, single author); liquidity vanished within minutes (news); price impact spiked and open interest cleared (preprint). Moderate-to-weak. | 1, 7 |
| 2 | If the order book is thin relative to our intended size (estimated slippage high), caution or stay out. | Slippage rises as depth falls (working paper); a slippage-at-risk measure related to later deficits (preprint). Weak-to-moderate; needs our own depth history, which is 2 days. | 7 |
| 3 | After an exploit becomes known, stay out for a window; treat on-chain anomalies as risk if they can be seen. | Tokens fall around hacks and part of the fall comes before the notice (working paper, conference paper, preprint). Moderate. We cannot see on-chain anomalies yet. | 6 |
| 4 | Flag funding that is extreme against the coin's own recent history. | One BTC study, low-tier venue, about returns after negative extremes. Weak; as a conditioning flag only. | 2 |
| 5 | Flag when the price from our reference venue disagrees with another venue or an aggregator beyond a tolerance; treat as bad data, not as a trade signal. | Venue-local dislocations on 2025-10-10 (industry) and cross-exchange gap literature (journal, preprint); our own 2026-08-23 case. Moderate for data quality. | 9 |
| 6 | Use a low leverage cap. | Margins sized on normal returns understate the needed margin in extreme-value tails (preprint). This supports the existing 3x cap; it is not a gate signal. | 1 |
| 7 | Treat recent realized volatility as a regime flag (high means caution). | Realized-volatility models forecast next-day volatility better than GARCH in one journal study. Weak: it supports forecasting volatility, not that a high-volatility flag avoids losses. | 4 |
| 8 | Caution in the weeks before and after a large scheduled unlock. | Industry report only, no significance tests. Weak; and we have no unlock calendar. | 5 |
| 9 | Taker order-flow variance compression as an early caution flag. | One preprint, BTC, placebo-tested at population level but not an alarm for single events. Very weak. | 1, 3 |

**Ideas with no support found** (in what I opened):
- Open interest level or fall as a crash predictor. It looks like a consequence of cascades.
- Long/short account or top-trader ratios as crash signals.
- Any single-variable early-warning signal that works in every cascade (the 2026 preprint finds none).
- A scalar pre-cascade leverage or fragility measure that grades severity (same preprint, negative).
- Extreme positive funding as a crash predictor.
- Any threshold value for any of the above.
- Token-unlock price impact on a small coin, from peer-reviewed work.
- Trusting an aggregator price as truth during a shock on a thin token.

## B. Baselines Gate 2 must beat

Only baselines the sources justify:
1. **A realized-volatility rule** (recent realized volatility above a limit means caution), with a HAR-style realized-volatility forecast as the stronger version. Justified by the volatility-forecasting study (HAR-RV beat GARCH), which also shows errors stay large.
2. **A funding-extreme rule** relative to the coin's own trailing history. Justified by the Binance funding paper, which defines its extremes that way. Weak source.
3. **The Gate 1 data rules themselves** (the 2% venue-disagreement exclusion and the known-at rules) as a floor: a gate that does not beat plain data hygiene adds nothing. This follows from the venue-gap literature and our own checks.

My own addition, not from a source: the two bookends "always stay out" and "always clear (no gate)". Every gate result should be reported next to them, and the number of variants tried should be reported alongside, as the deflated-Sharpe and backtest-overfitting papers require.

## C. What the sources say about our situation

We have about 7 episodes in 491 days, one coin, and recorder features with 32 days of history, only about 1 day captured live (docs/gate1_summary.md).
- The best-designed study I opened on early-warning signals (seven BTC cascades, years of free five-minute data) still found that no signal works in every event, effects are moderate, and single-event claims are fragile. We have fewer events, a thinner coin, and shorter order-flow history.
- Hold-out testing is unreliable in small samples (Bailey et al.). With so few episodes any tuned rule will fit them, and the number of variants tried must be counted.
- Hack studies use 22 to 49 events across many protocols; we have two exploits on one coin.

Claims we **cannot** make:
- That any rule predicts crashes on TAC. We have no evidence for that.
- That a backtest result, however good, shows the gate works; at best it shows the gate would have behaved sensibly in about seven episodes.
- Any statistical significance of a signal on TAC, or a generalisation to other coins.
- That recorder features (open interest, long/short, taker flow, depth) are useful, until they have far longer history.
- A cause for any of our big moves; the cause of the 2026-08-22 price fall is not established by anything here.

One unverified lead: the 2026 preprints say they used free 5-minute Binance metrics files for open interest, long/short and taker data. Whether such files exist for TACUSDT, and how far back, has not been checked.

## D. Search log

Web searches (16): liquidation cascades and leverage in perpetuals; funding rate and returns; open interest and long/short ratio and crashes; Bitcoin volatility forecasting (HAR, GARCH); token unlocks price impact (twice, the second aimed at academic work); hacks and token price; order book depth and slippage; probability of backtest overfitting and deflated Sharpe ratio; purged and walk-forward cross-validation; price discrepancies on 2025-10-10; cross-exchange deviations and limits to arbitrage; extreme funding and subsequent returns; crypto carry; open interest and extreme declines; low-liquidity altcoin perpetual manipulation.

Opened (25 pages or PDFs): the 24 sources cited above plus one dropped (arXiv 2601.06084). Five arXiv PDFs would not read through the page fetcher, so I downloaded them and extracted the text locally.

Could not open: both SSRN abstract pages (HTTP 403), the Springer page for a 2023 Bitcoin crash-risk paper (login redirect), a core.ac.uk volatility paper (403), an MDPI Bitcoin order-book paper (403), a Kaiko research note (redirect to a login app), the Wikipedia page on purged cross-validation (404), and the BIS full PDF (no readable text; the landing page was used).

Seen in search results only, **not opened and not used:** a 2022 GARCH-versus-HAR Bitcoin paper, two SSRN papers on funding-rate predictability and asymmetry, the SSRN listing of the crypto carry paper, a 2025 conference listing with an open-interest odds ratio, long/short ratio posts from The Block and CryptoQuant, token-unlock blog posts, manipulation write-ups on thin perpetuals, and a purged cross-validation tutorial set.
