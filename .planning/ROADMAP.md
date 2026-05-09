# Antariksh Phase 2 Roadmap — Multi-Crew Ralph Loop Architecture

**All phases: TDD — tests first, build after review.**

## Phase 1: Ralph Loop Infrastructure Tests + OM Crew
**Goal:** Foundation verification + Operations Manager (infra watchdog)
**Mode:** mvp
**Requirements:** RAL-01 to RAL-04, OPS-01 to OPS-08
**Success Criteria:**
1. 4 Ralph Loop tests pass (scheduled PRD check, YAML loading, auto-escalation, PRD evolution)
2. 17 OM tests pass (token refresh, code verification, data capture, disk, network, crons, health report)
3. OM crew can run pre-market readiness checklist independently
4. Ralph Loop cycle (run → verify → feedback → repeat) executes without errors

## Phase 2: Trading Analyst Crew
**Goal:** Trade execution validation bridge (PM spec ↔ AM financials)
**Mode:** mvp
**Requirements:** TRA-01 to TRA-07
**Success Criteria:**
1. 15 TA tests pass (strategy spec validation, compliance reporting, execution ledger)
2. TA catches all strategy spec violations in test scenarios
3. TA correctly routes compliance report → PM, execution ledger → AM

## Phase 3: Portfolio Manager Crew
**Goal:** Strategy ownership (IB/Credit Spread selection, indicator weights)
**Mode:** mvp
**Requirements:** PM-01 to PM-07
**Success Criteria:**
1. 12 PM tests pass (strategy selection, spec generation, indicator weighting)
2. PM produces valid strategy specs consistent with antariksh_rules.yaml
3. PM respects resource limits (max 2 strategies, 8 indicators)

## Phase 4: Asset Manager Crew
**Goal:** Financial oversight (P&L, margin, burn rate, capital preservation)
**Mode:** mvp
**Requirements:** AM-01 to AM-07
**Success Criteria:**
1. 11 AM tests pass (P&L tracking, margin monitoring, burn trends)
2. AM enforces capital preservation limits (daily SL, portfolio SL, capital floor)
3. AM correctly rejects orders exceeding resource limits

## Phase 5: Post-Mortem Analyst Crew
**Goal:** Trade review and strategy improvement feedback loop
**Mode:** mvp
**Requirements:** PA-01 to PA-06
**Success Criteria:**
1. 14 PA tests pass (trade reviews, counterfactuals, what-if P&L)
2. PA generates actionable improvement recommendations for PM
3. PA correctly tags anomalous trades

## Phase 6: CEO Crew + Governance
**Goal:** Alignment guardian + board reporting
**Mode:** mvp
**Requirements:** CEO-01 to CEO-06, GA-01 to GA-15
**Success Criteria:**
1. 20 CEO tests pass (alignment checks, performance aggregation, resource enforcement)
2. 15 Governance tests pass (authority chain, escalation path)
3. CEO board report aggregates all crew reports correctly
4. CEO enforces resource caps without exception

## Phase 7: Inter-Crew Communication Wire-up
**Goal:** All crews communicate via agreed protocol
**Mode:** mvp
**Requirements:** INT-01 to INT-08, remaining Ralph Loop integration tests
**Success Criteria:**
1. 12 integration tests pass (all crew-to-crew interfaces)
2. File-based or shared-state communication protocol selected and validated
3. Full Ralph Loop cycle across all crews runs end-to-end
4. Parallel Phase 1 (live) + Phase 2 (shadow) deployment verified

## Traceability

| Category | REQ-IDs | Phase |
|----------|---------|-------|
| Operations Manager | OPS-01 to OPS-08 | 1 |
| Ralph Loop | RAL-01 to RAL-06 | 1, 7 |
| Trading Analyst | TRA-01 to TRA-07 | 2 |
| Portfolio Manager | PM-01 to PM-07 | 3 |
| Asset Manager | AM-01 to AM-07 | 4 |
| Post-Mortem Analyst | PA-01 to PA-06 | 5 |
| CEO | CEO-01 to CEO-06 | 6 |
| Governance | GA-01 to GA-15 | 6 |
| Integration | INT-01 to INT-08 | 7 |
| **Total** | **66 requirements** | **7 phases** |
