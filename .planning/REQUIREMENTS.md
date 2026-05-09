# Antariksh — v1 Requirements (Phase 2: Multi-Crew Ralph Loop)

## Operations Manager (OM)
- [ ] **OPS-01**: Token refresh — validate broker tokens before market open
- [ ] **OPS-02**: Code verification — verify no unauthorized code changes since last session
- [ ] **OPS-03**: Data capture health — verify DuckDB market data stream is running
- [ ] **OPS-04**: Disk check — verify sufficient free space for logs/exec reports
- [ ] **OPS-05**: Network check — verify broker API reachability
- [ ] **OPS-06**: Cron health — verify 9:30 AM and 2:35 PM crons are active
- [ ] **OPS-07**: System health report → CEO (uptime, broker status, infra green/red)
- [ ] **OPS-08**: Pre-market readiness checklist (all checks pass → GO signal)

## Trading Analyst (TA)
- [ ] **TRA-01**: Validate every trade against PM strategy spec (type, strikes, wings, lots)
- [ ] **TRA-02**: Validate SL and TSL placement matches PM spec exactly
- [ ] **TRA-03**: Validate indicator conditions at entry match PM spec
- [ ] **TRA-04**: Report violations to PM with severity (compliance report)
- [ ] **TRA-05**: Report execution ledger to AM (P&L, broker, fees, slippage)
- [ ] **TRA-06**: Validate order fill price within acceptable slippage range
- [ ] **TRA-07**: Check no duplicate trades within same session

## Portfolio Manager (PM)
- [ ] **PM-01**: Strategy selection (IB/Credit Spread) based on indicator weight scoring
- [ ] **PM-02**: Define strategy spec (type, strikes, wings, lots, SL, TSL, indicators)
- [ ] **PM-03**: Apply ATM rules and strike distance calculations
- [ ] **PM-04**: Incorporate PA feedback into strategy adjustments
- [ ] **PM-05**: Report strategy summary to CEO (WR%, PF)
- [ ] **PM-06**: Send strategy spec to TA for execution validation
- [ ] **PM-07**: Respect resource limits (max 2 strategies, 8 indicators)

## Asset Manager (AM)
- [ ] **AM-01**: Track cumulative P&L (daily, MTD, annual progress toward ₹36L)
- [ ] **AM-02**: Monitor available margin and capital allocation
- [ ] **AM-03**: Track broker costs and burn rate trends
- [ ] **AM-04**: Enforce capital preservation limits (₹3,500 daily SL, ₹4,500 portfolio SL)
- [ ] **AM-05**: Enforce capital floor (₹11,000 free cash minimum)
- [ ] **AM-06**: Report capital status to PM (available margin, burn rate)
- [ ] **AM-07**: Report financial summary to CEO

## Post-Mortem Analyst (PA)
- [ ] **PA-01**: Review all completed trades against their strategy specs
- [ ] **PA-02**: Run counterfactuals — alternative entry/exit/TP/SL scenarios
- [ ] **PA-03**: Calculate "what-if" P&L for alternative decisions
- [ ] **PA-04**: Identify recurring violation patterns
- [ ] **PA-05**: Recommend strategy improvements to PM
- [ ] **PA-06**: Tag trades for deeper analysis (anomalous outcomes)

## CEO
- [ ] **CEO-01**: Alignment check — every crew decision against vision/mission/goals
- [ ] **CEO-02**: Aggregate crew performance metrics (compliance %, uptime %, WR%, PF, DD)
- [ ] **CEO-03**: Enforce resource caps (max positions, max capital, max strategies)
- [ ] **CEO-04**: Generate board report (aggregated summary for Chairman)
- [ ] **CEO-05**: Escalate violations/breaches to Chairman
- [ ] **CEO-06**: Does NOT direct strategy (PM's domain) or execute trades

## Ralph Loop Governance
- [ ] **RAL-01**: Scheduled PRD verification — run every session against all applicable PRDs
- [ ] **RAL-02**: YAML loading — load constitution, PRDs, and all yaml configs
- [ ] **RAL-03**: Auto-escalation — escalate repeated PRD failures to Chairman
- [ ] **RAL-04**: PRD evolution — track PRD metric history, suggest min_samples updates
- [ ] **RAL-05**: Crew-to-crew PRD pass/fail aggregation
- [ ] **RAL-06**: Ralph loop cycle: run → verify → feedback → repeat

## Inter-Crew Communication (design pending)
- [ ] **INT-01**: PM → TA: strategy spec delivery mechanism
- [ ] **INT-02**: TA → PM: compliance report delivery mechanism
- [ ] **INT-03**: TA → AM: execution ledger delivery mechanism
- [ ] **INT-04**: AM → PM: capital report delivery mechanism
- [ ] **INT-05**: AM → CEO: financial summary delivery mechanism
- [ ] **INT-06**: PM → CEO: strategy summary delivery mechanism
- [ ] **INT-07**: OM → CEO: infra summary delivery mechanism
- [ ] **INT-08**: CEO → Board: aggregated board report mechanism

### v2 Requirements (deferred)
- Full autonomy trust ladder (L0→L4)
- Multi-instrument (SENSEX)
- MCX evening session
- Multiple simultaneous strategies
- Real-time streaming MTM (currently Two-Message Protocol only)

### Out of Scope
- Manual trading interface — system is autonomous only
- Non-Indian markets — NIFTY/SENSEX only
- Real-time streaming dashboard — Two-Message Protocol only
- Risk decisions by agent judgment — all risks are code-gated
