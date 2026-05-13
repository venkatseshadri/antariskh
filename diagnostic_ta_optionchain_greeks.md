# TA — Option Chain & Greeks Diagnostics

Date: 2026-05-11
Repository: `/home/trading_ceo/python-trader`

## 1. Option Chain — Tests

**Yes.** Shoonya SDK has option chain test at:

`ShoonyaApi-py/tests/test_optionchain.py:24-39`
```python
def getLastQuoteOptionChain(exchange, tradingsymbol, strikeprice, count=10):
    chain = api.get_option_chain(exchange=exch, tradingsymbol=tsym,
                                 strikeprice=strikeprice, count=count)
    # parallel-fetches live quotes via ThreadPoolExecutor
```

- Calls `api.get_option_chain()` on NFO exchange
- Parallel quote fetch via `ThreadPoolExecutor(max_workers=10)`
- Broker SDKs with `get_option_chain`:
  - `ShoonyaApi-py` (legacy auth)
  - `Shoonya_oAuthAPI-py` (OAuth)
  - `Shoonya_oAuthAPI-py-main` (OAuth main)
  - `FlattradeApi-py` (Flattrade)

## 2. Greeks — Tests

**Yes, two paths:**

### Path A: Broker API (Shoonya endpoint)
`ShoonyaApi-py/tests/test_GetOption_Greek.py:20`
```python
ret = api.option_greek(expiredate='24-NOV-2022', StrikePrice='150',
                       SpotPrice='200', InterestRate='100',
                       Volatility='10', OptionType='CE')
```
Also tested with OAuth variant at `Shoonya_oAuthAPI-py-main/tests/test_GetOption_Greek.py`.

### Path B: Local Black-Scholes (Python)
`varaha_advanced_indicators.py:192-241`
```python
def _black_scholes_greeks(S, K, T, r, sigma, option_type='C') -> Dict:
    # Uses scipy.stats.norm for d1/d2 calculation
    # Returns {'delta': float, 'gamma': float, 'vega': float, 'theta': float}
```

`varaha_advanced_indicators.py:244` — `compute_aggregate_greeks(db, spot, expiry, atm_strike, vix)`:
- Computes position-level Greeks for Iron Fly (wings long + ATM straddle short)
- Outputs: `agg_delta`, `agg_gamma`, `agg_vega`, `agg_theta`, `wings_delta`, `body_delta`

## 3. DuckDB — Option Chain & Greeks Present

### `option_snapshots` table (raw option chain)

Defined at `varaha/data_capture_v3_duckdb.py:519-534`:

| Column | Type | Description |
|---|---|---|
| `timestamp` | TEXT | Capture timestamp |
| `date` | TEXT | Date string |
| `expiry_label` | TEXT | e.g. 'weekly', 'monthly' |
| `expiry_date` | TEXT | Expiry date |
| `strike` | INTEGER | Strike price |
| `strike_offset` | INTEGER | Offset from ATM (e.g. 0, 50, -100) |
| `option_type` | TEXT | CE or PE |
| `ltp` | DOUBLE | Last traded price |
| `volume` | BIGINT | Volume |
| `oi` | BIGINT | Open interest |
| `iv` | DOUBLE | Implied volatility |

Indexes: `idx_os_chain` on `(timestamp, expiry_label, strike_offset)`, `idx_os_date` on `(date)`.

### `market_data` table (aggregate Greeks columns)

Added as migration columns at `varaha/data_capture_v3_duckdb.py:579-585`:

| Column | Type | Description |
|---|---|---|
| `agg_delta` | DOUBLE | Net directional exposure |
| `agg_gamma` | DOUBLE | Curvature risk (negative for short) |
| `agg_vega` | DOUBLE | IV sensitivity (negative for short) |
| `agg_theta` | DOUBLE | Time decay (positive for short) |
| `wings_delta` | DOUBLE | Hedge legs delta |
| `body_delta` | DOUBLE | ATM straddle delta |

Computed each capture cycle by `compute_aggregate_greeks()` → stored in `market_data`.

## 4. Database Files

| Database | Path | Contents |
|---|---|---|
| NIFTY | `varaha/data/varaha_data.duckdb` | 1,107 market_data + 32,648 option_snapshots (2026-05-04 to 05-06) |
| SENSEX | `varaha/data/varaha_data_sensex.duckdb` | 1,099 market_data + 30,008 option_snapshots (2026-05-05 to 05-06) |

## Summary

- [x] Option chain via broker (`get_option_chain`) — tests exist in ShoonyaApi-py
- [x] Greeks via broker (`option_greek`) — tests exist in ShoonyaApi-py
- [x] Greeks via local Black-Scholes — `varaha_advanced_indicators.py`
- [x] Option chain in DuckDB — `option_snapshots` table with strike/iv/ltp/oi/volume
- [x] Greeks in DuckDB — `market_data` table with agg_delta/gamma/vega/theta
