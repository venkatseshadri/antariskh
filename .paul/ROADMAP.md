# Antariksh Phase 2 Roadmap

**All phases: TDD — tests first, build after review. PAUL loop: PLAN → APPLY → UNIFY per phase.**

## Phase 1: Ralph Loop Infrastructure Tests + OM Crew
**Goal:** Foundation verification + Operations Manager (infra watchdog)
**Mode:** mvp
**Requirements:** RAL-01..04, OPS-01..08
**Success Criteria:**
1. 4 Ralph Loop tests pass (scheduled PRD check, YAML loading, auto-escalation, PRD evolution)
2. 17 OM tests pass (token refresh, code verification, data capture, disk, network, crons, health report)
3. OM crew runs pre-market readiness checklist independently (8:00 AM cron, Telegram evidence report)
4. Ralph Loop cycle (run → verify → feedback → repeat) executes without errors

## Phase 2: Trading Analyst Crew
**Goal:** Trade execution validation bridge (PM spec ↔ AM financials)
**Requirements:** TRA-01..07
**Success Criteria:**
1. 15 TA tests pass
2. TA catches all strategy spec violations
3. TA correctly routes compliance report → PM, execution ledger → AM

## Phase 3: Portfolio Manager Crew
**Goal:** Strategy ownership (IB/Credit Spread selection, indicator weights)
**Requirements:** PM-01..07
**Success Criteria:**
1. 12 PM tests pass
2. PM produces valid strategy specs consistent with antariksh_rules.yaml
3. PM respects resource limits (max 2 strategies, 8 indicators)

## Phase 4: Asset Manager Crew
**Goal:** Financial oversight (P&L, margin, burn rate, capital preservation)
**Requirements:** AM-01..07
**Success Criteria:**
1. 11 AM tests pass
2. AM enforces capital preservation limits
3. AM rejects orders exceeding resource limits

## Phase 5: Post-Mortem Analyst Crew
**Goal:** Trade review and strategy improvement feedback loop
**Requirements:** PA-01..06
**Success Criteria:**
1. 14 PA tests pass
2. PA generates actionable recommendations for PM
3. PA correctly tags anomalous trades

## Phase 6: CEO Crew + Governance
**Goal:** Alignment guardian + board reporting
**Requirements:** CEO-01..06, GA-01..15
**Success Criteria:**
1. 20 CEO tests + 15 governance tests pass
2. CEO board report aggregates all crew reports
3. CEO enforces resource caps without exception

## Phase 7: Inter-Crew Communication Wire-up
**Goal:** All crews communicate via agreed protocol
**Requirements:** INT-01..08, remaining Ralph Loop integration
**Success Criteria:**
1. 12 integration tests pass
2. Communication protocol selected and validated
3. Full Ralph Loop cycle across all crews runs end-to-end
4. Parallel Phase 1 (live) + Phase 2 (shadow) deployment verified

## Traceability
| Category | REQ-IDs | Phase |
|----------|---------|-------|
| Operations Manager | OPS-01..08 | 1 |
| Ralph Loop | RAL-01..04 | 1 |
| Trading Analyst | TRA-01..07 | 2 |
| Portfolio Manager | PM-01..07 | 3 |
| Asset Manager | AM-01..07 | 4 |
| Post-Mortem Analyst | PA-01..06 | 5 |
| CEO | CEO-01..06 | 6 |
| Governance | GA-01..15 | 6 |
| Integration | INT-01..08 | 7 |
