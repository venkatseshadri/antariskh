# System Readiness — Verified 2026-07-26 (pre Jul-27 open)

Source: /tmp/system_readiness_concerns.md (untrusted, unattributed "System Audit") cross-checked against live systems by Claude. Table below: file's claim vs actual verified state.

## Broker sessions

| Broker | File claimed | Verified live | Evidence |
|---|---|---|---|
| Shoonya | ✅ Reachable | ❌ **Session expired** | `broker_manager.get_broker_manager()` → login fails; `get_limits()` → `{'stat':'Not_Ok','emsg':'Session Expired : Invalid Session Key'}` |
| Flattrade | ❌ Unreachable | ✅ **Valid, live** | Direct `NorenApi.get_limits()` w/ current token (`python-trader/tokens.json`, last_login 2026-07-25 08:13) → `stat: Ok`, collateral ₹9843.23 |

File had both broker rows **backwards**. Do not trust it for broker status.

Bonus bug found: `brahmand/broker_manager.py:81` `Flattrade.load_token()` reads key `"token"`, but `python-trader/tokens.json` stores it as `"access_token"` → BrokerManager always sees Flattrade as unavailable even when session is valid. Cosmetic/logic bug, not a real outage. Not fixed (validator role — flag only).

## Data pipeline

**Confirmed stale**, file's core claim holds:
- `preflight_health.py` (re-run live): `NOGO: 2 checks failed` — capture_nifty/capture_sensex enriched freshness last row `2026-07-21T15:29:00`
- Heartbeats in `antariksh/data/live/*.heartbeat`: NIFTY/SENSEX/INDIAVIX stuck at Jul 21 15:29-15:30, MCX stuck Jul 21 23:29-23:30, multitf_enricher_NIFTY/SENSEX newer (Jul 24 15:55) but still 2 days stale
- **Not a simple "feed down" story**: `journalctl -u feed.service` shows it *started and ran* normally Jul 23 09:14 and Jul 24 09:14 (full sessions, restarted several times Jul 24 evening). Process was alive; heartbeats/enriched writes still died mid-session. Matches known bug pattern already in memory (`feed_producer_silent_crash_loop` — WS callback dies silently while systemd shows active). Root cause is the silent-crash class, not "pipeline never started."
- feed.service currently inactive (exec-condition, expected — Sunday, no market). Will attempt normal start Mon 09:14 per timer; whether Monday's run survives past open is the real open question, not addressed by this file.

## NUCLEUS capital pool

**Confirmed**, file is right:
- `antariksh/data/nucleus_allocation.json`: `pool_total: 0.0`, all 4 tier ceilings `0.0`, `updated_at: 2026-07-24T15:58:02`
- `antariksh/logs/nucleus_cron_20260724.log`: 0 bytes — cron ran (file exists, dated) but produced no log output, consistent with early silent failure
- Effect confirmed: any tier gated on NUCLEUS ceiling > 0 will refuse entries until this is fixed regardless of data-pipeline recovery

## PROTON+ / HYDROGEN data dirs

Dirs exist (`antariksh/data/proton`, `antariksh/data/hydrogen`, plus matching `logs/` dirs) — did not verify emptiness/contents claim in depth; not re-checked line by line. Treat file's "EMPTY, no state file" claim as **unverified**, not confirmed false either.

## Ralph build loop / GitHub 401

`ralph-sched.service` inactive since 2026-06-01 (1.5 months, matches memory: SHERPA/DAMBUILDER era pause, not new). Searched journal for 401/GitHub errors — none found in retained journal (likely rotated out). File's "Ongoing GitHub 401" claim: **unverified**, can't confirm or deny from current logs.

## Infra

Roughly confirmed:
- Disk: 42GB free / 57% used — matches
- Memory: 4.7Gi available of 7.8Gi total (file said 4.6Gi) — matches within rounding; swap 1.5Gi/4Gi in use, worth a glance but not flagged as blocking

## Net verdict

NOT READY for Monday open, but for different top-line reasons than the file states:

1. **Shoonya session dead** (file said fine) — must re-login before 09:15 IST. Blocks ATOM+ and PROTON+ (both Shoonya-based per prior sessions).
2. **Flattrade session fine** (file said dead) — HYDROGEN/NEUTRON broker connectivity is not the blocker.
3. **Data pipeline stale since Jul 21**, confirmed, but process-level story is "silent crash while alive," not "never restarted" — check for the WS-callback-death signature specifically Monday morning, not just whether feed.service is Active.
4. **NUCLEUS pool = 0** confirmed — separate fix needed (nucleus.py output silently failing), blocks PROTON+ entries even if #1 and #3 are fixed.
5. NEUTRON open position (Jul 23 entry, expires Jul 28 Tue) — not independently re-verified this pass, carried over from file as-is.

## Recovery steps (revised)

1. Re-login Shoonya (session expired, not "reachable and fine")
2. Investigate feed.py silent-crash signature Monday at/after 09:14 — don't just check `systemctl is-active`, check heartbeat file mtimes are advancing
3. Debug why `nucleus.py` writes `pool_total: 0.0` / empty cron log — likely swallowing an exception
4. Do NOT restart Flattrade connectivity — it's not broken
5. Re-run `preflight_health.py` after 1-2 fixed, confirm GO
6. Re-verify PROTON+/HYDROGEN data dir contents directly (unverified in this pass)
