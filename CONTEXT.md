# SESSION CONTEXT — Updated 2026-05-20 (May 19 EOD + Margin Integration)

Project: Antariksh — CrewAI options trading desk (NIFTY Iron Butterfly)
Branch: `master` | Live data: VIX=18.53, NIFTY=23604.3, Regime=TRENDING_BEAR

## Locations
```
/home/trading_ceo/antariksh/              ← Antariksh (trading desk)
/home/trading_ceo/brahmand/               ← Brahmand (data/orders)
/home/trading_ceo/python-trader/varaha/   ← Varaha (DuckDB capture)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/  ← Shoonya API
```
GitHub: `github.com/venkatseshadri/antariskh`

## Last Built (May 19-20)
✅ Complete 7-agent trading system with Order Agent hub, safe broker integration (margin fetch at 07:00 cron), zero hardcoding (risk_config.py), dynamic registries. **System ready for May 20 market.**

See: [[seven_agent_system_complete]] memory file for complete details.

## Priority Queue (Next)
1. **Test margin fetch** — Run token_refresh_dual.py at 07:00, verify /tmp/broker_limits.json created
2. **Implement Flattrade margin** — Placeholder at token_refresh_dual.py:170 (low priority)
3. **EMA backfill wiring** — Integrate ema_backfill into data_capture_v4, ema_integration_hook live updates

## Key Files (May 20 Build)

**Core System**:
- `trading_desk.py` — 7 agents + 4-phase crew + registry init
- `order_agent.py` — Central order hub + ledger (/tmp/order_ledger.json)
- `risk_config.py` — All limits (ZERO hardcoding), hot-reload functions
- `broker_limits.py` — Fetch live margins, cache, sync to config
- `agent_registry.py` — 7 agents discoverable
- `tools_registry.py` — 10 tools discoverable

**Integration**:
- `token_refresh_dual.py` — 07:00 cron: tokens + margin fetch (integrated)
- `leg_shifter.py` — Uses Order Agent for shift orders
- `position_manager.py` — MORPH detection

**Docs**:
- `AGENTS_SPECIFICATION.md` — Knowledge for all 7 agents
- `ORDER_AGENT_INTEGRATION.md` — Order Agent architecture
- `SYSTEM_INTEGRATION_GUIDE.md` — How everything works
- `BROKER_API_SAFETY.md` — API rate-limit principles
- `MARGIN_FETCH_INTEGRATION.md` — 07:00 cron margin capture

## Verify State (May 20)
```bash
cd /home/trading_ceo/antariksh

# Check system is intact
python3 -c "from risk_config import get_config_summary; print(get_config_summary())"
python3 -c "from agent_registry import list_agents; print(list_agents())"

# Check Order Agent works
python3 /home/trading_ceo/brahmand/order_agent.py --test

# Check broker integration
python3 -c "from broker_limits import get_current_limits; limits, fresh = get_current_limits(); print(f'Limits: {limits}, Fresh: {fresh}')"

# Full trading desk
python3 trading_desk.py --full-session
```

## Recent Commits (May 19-20)
```
7881f5a docs: update session context and roadmap (May 19 EOD)
1c421e0 docs: add SESSION_20260519.md — full session capture with active trade, discoveries, pipeline state
4cb00d4 fix: paper mode — take ALL trades including MOMENTUM_PEAK
fda816a feat: datacapture v3.1 + v4 validation complete — zero data loss

Next commit (May 20):
→ feat: 7-agent system + Order Agent hub + safe broker integration (margin at 07:00 cron)
```
