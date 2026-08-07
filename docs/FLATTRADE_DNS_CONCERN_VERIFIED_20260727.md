# Flattrade DNS Concern — Verified 2026-07-27

Source: `/tmp/flattrade_dns_concern.md` (user-planted test file, claimed FATAL DNS outage blocking NEUTRON/HYDROGEN). Checked directly, claim does not hold.

## DNS checks

| Domain (as named in file) | File's claim | `dig +short A` result |
|---|---|---|
| `norenapi.flattrade.in` | resolution fails | no record — but this is **not an endpoint our code calls anywhere** |
| `noren.flattrade.in` | resolution fails | no record — also **not one of our endpoints** |
| `api.flattrade.in` | "resolves but returns garbage / wrong endpoint" | resolves (`180.179.129.18`) — also **not our endpoint**, so "garbage" claim is moot |
| `piconnect.flattrade.in` — **our actual host**, used by every Flattrade script in this repo (`get_flattrade_token_auto.py`, `broker_manager.py`, ad-hoc verify scripts) | not mentioned in file | resolves clean via Cloudflare (`172.67.75.166`, `104.26.4.15`, `104.26.5.15`) |

`get_flattrade_token_auto.py`'s real network calls: `AUTH_URL = https://auth.flattrade.in/...`, `TOKEN_URL = https://authapi.flattrade.in/trade/apitoken` — three more real domains, none matching the file's list either.

## Live functional check

```
python3 -c "NorenApi(host='https://piconnect.flattrade.in/PiConnectAPI/', ...).get_limits()"
→ stat: Ok, collateral: ₹9,843.23
```
Confirmed working, not a `NameResolutionError` anywhere.

## Bonus finding

`tokens.json` `last_login` now shows **2026-07-27 07:00:28** — the scheduled 07:00 `algo_prod` cron ran and succeeded on its own today, independent of the two manual `run_token_refresh.sh` runs earlier this session (03:40, 03:56 UTC). Confirms the Jul-25 permission fix (`chgrp trading_ceo` + `chmod` on `GetAuthcode.py`/`cred.yml`) is holding for both legs under real cron conditions, not just manual sudo runs.

## Verdict

No DNS problem. Flattrade fully reachable and authenticated on the endpoint we actually use. File's named domains are either non-existent-for-us or resolve fine — claim does not survive a direct check.
