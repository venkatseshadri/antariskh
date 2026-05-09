# 🎯 START HERE — DeepSeek Weekend Execution Package
**Read this first. Everything you need is in these 6 documents.**

---

## Your Mission

**By Sunday 11:59 PM IST:**
- ✅ Fix 3 critical blockers (2 hours)
- ✅ Implement 4 optional tests (3 hours)
- ✅ Validate everything (2 hours)
- ✅ Create deployment checklist (1 hour)

**Outcome:** System ready for Monday 9:30 AM live trading.

---

## 📚 Your Handoff Package (Read in This Order)

### 1️⃣ **START: CLAUDE_MASTER_HANDOFF.md** (15 min read)
**What:** Executive summary of current system state + blockers + timeline  
**Contains:** What works (18 tests pass), what's broken (1 fail, 13 notest), what you need to do  
**Decision:** Is this doable? (Answer: Yes, 8-10 hours focused work)

### 2️⃣ **CRITICAL: CRITICAL_FIXES_REQUIRED.md** (30 min read + 2 hour implement)
**What:** Exactly how to fix the 3 blockers that block Monday live  
**Contains:** Copy-paste code, exact file locations, test commands  
**Action:** Do this FIRST before anything else. Tests must pass after.

### 3️⃣ **EXECUTION: DEEPSEEK_EXECUTION_PLAN.md** (30 min read + 6 hours implement)
**What:** Step-by-step task breakdown in priority order  
**Contains:** 4 phases (critical, strong, validation, deployment)  
**Action:** Follow exactly. Tick off tasks as you complete them.

### 4️⃣ **TRACKING: DEEPSEEK_STATUS_LOG.md** (ongoing, update every 2 hours)
**What:** Your progress log (fill in as you work)  
**Contains:** Template for documenting what you did, tests run, issues found  
**Action:** Update this file as you work. Claude will read it.

### 5️⃣ **SPEC: PHASE_1_DEPLOYMENT_SPEC.md** (20 min read, reference throughout)
**What:** Exactly what must work Monday 9:30 AM  
**Contains:** 10 critical requirements, each with test case  
**Action:** Use as checklist. Everything links to a test that proves it works.

### 6️⃣ **REFERENCE: SCENARIO_TEST_PLAN.md** (optional, read as needed)
**What:** Comprehensive spec of all 32 scenarios  
**Contains:** What each scenario tests, expected behavior, pass/fail criteria  
**Action:** Read when implementing specific tests.

---

## ⚡ Quick Start (Next 30 Minutes)

```bash
# 1. Read CLAUDE_MASTER_HANDOFF.md (~15 min)
cat /home/trading_ceo/antariksh/CLAUDE_MASTER_HANDOFF.md | head -100

# 2. Understand the 3 blockers (~5 min)
cat /home/trading_ceo/antariksh/CRITICAL_FIXES_REQUIRED.md | head -50

# 3. Start implementing BLOCKER #1 (~30 min)
# See CRITICAL_FIXES_REQUIRED.md BLOCKER #1: Event Calendar

# 4. Test BLOCKER #1
pytest tests/test_scenarios.py::test_HP_04_gate_skip_event_day -v

# 5. Move to BLOCKER #2 when #1 passes
```

---

## 📊 Success Metrics (Track These)

### By Sunday 23:59 PM
- [ ] **3/3 Critical Blockers Fixed**
  - [ ] Event Calendar (HP-04 PASS)
  - [ ] ScenarioRunner MOCK_MODE (MC-01 runs)
  - [ ] RM-02 Test (RM-02 PASS)

- [ ] **25+/32 Tests Passing**
  - [ ] HP: 3/4 passing (HP-02 optional)
  - [ ] RM: 5/6 passing
  - [ ] DD: 2/4 passing
  - [ ] OP: 3/3 passing
  - [ ] LC: 3/3 passing
  - [ ] EC: 2/2 passing

- [ ] **Critical Validations**
  - [ ] No syntax errors: `python3 -c "from antariksh import crew_structure"`
  - [ ] JSONL logs written: `ls logs/cfo_audit_*.jsonl`
  - [ ] Deployment checklist complete

### Result: 🟢 READY FOR MONDAY 9:30 AM

---

## 🛠️ Tools & Commands You'll Need

### Run tests:
```bash
cd /home/trading_ceo/antariksh
export PYTHONPATH=/home/trading_ceo:$PYTHONPATH

# Single test
pytest tests/test_scenarios.py::test_HP_04_gate_skip_event_day -v

# All critical tests
pytest tests/test_scenarios.py -k "HP or RM or DD or OP or LC or EC" -v

# Full suite
pytest tests/test_scenarios.py -v
```

### Debug:
```bash
# Check imports
python3 -c "from antariksh import crew_structure"

# Check event calendar
python3 -c "import json; print(json.load(open('config/event_calendar.json'))['rbi_events'][:2])"

# Check syntax
python3 -m py_compile crew_structure.py tests/test_scenarios.py
```

### Commit & push:
```bash
git add -A
git commit -m "[BLOCKER] Event Calendar: FIXED — is_event_day() reads config/event_calendar.json"
git log --oneline | head -5
```

---

## 📝 Handoff Communication Protocol

### You Write (Update as you work):
- **File:** `DEEPSEEK_STATUS_LOG.md`
- **When:** Every 2 hours
- **What:** Task completed, test status, blockers encountered

### Claude Reads (When checking in):
- **File:** `DEEPSEEK_STATUS_LOG.md`
- **When:** Daily or when pinged
- **Response:** Issues documented in `/home/trading_ceo/antariksh/CLAUDE_RESPONSE_LOG.md`

### Git Commits (Your voice):
- **Message format:** `[TAG] {feature}: {status} — {evidence}`
- **Tags:** `[BLOCKER]`, `[TEST]`, `[FIX]`, `[VALIDATION]`
- **Example:** `[BLOCKER] Event Calendar: FIXED — HP-04 test PASS`

---

## 🎯 Timeline (Realistic Estimate)

### Friday 10:00 AM → Saturday 2:00 AM (16 hours available)

```
Hour 0-2:   Read handoff docs (CRITICAL_FIXES_REQUIRED.md focus)
Hour 2-3:   BLOCKER #1: Event Calendar (test HP-04)
Hour 3-4:   BLOCKER #2: ScenarioRunner MOCK_MODE (test MC-01)
Hour 4-5:   BLOCKER #3: RM-02 Test (test RM-02)
            ↓ RUN FULL SUITE: pytest tests/test_scenarios.py -v
Hour 5-7:   OPTIONAL: HP-02, RM-03, RM-06 (if time)
Hour 7-8:   VALIDATION: JSONL, syntax, imports
Hour 8-9:   DEPLOYMENT_CHECKLIST creation + sign-off
Hour 9-10:  Buffer for unexpected issues

READY: Sunday 23:59 IST ✅
```

---

## ❓ When You Get Stuck

**Priority order to check:**

1. **Re-read the relevant section** (CRITICAL_FIXES_REQUIRED.md usually has the answer)
2. **Compare with passing test** (e.g., RM-01 if you're implementing RM-02)
3. **Google the error message** (Python, pytest errors are well-documented)
4. **Check git diff** to see what changed
5. **Add print() statements** to understand flow
6. **Document blocker** in DEEPSEEK_STATUS_LOG.md and move on
7. Claude will read and respond (within 4-6 hours)

**Never:** Spend >30 min stuck on one thing. Move on, come back later.

---

## ✅ Sunday 23:55 PM Checklist (Final Validation)

Before you close the laptop:

```bash
# 1. Run full test suite
cd /home/trading_ceo/antariksh
pytest tests/test_scenarios.py -v

# Expected:
# =========== 25+ passed ===========

# 2. Check syntax
python3 -m py_compile crew_structure.py tests/test_scenarios.py

# 3. Check imports
python3 -c "from antariksh import crew_structure; from antariksh.tests import test_scenarios; print('✅ All OK')"

# 4. Check JSONL
ls -la logs/cfo_audit_*.jsonl
cat logs/cfo_audit_*.jsonl | python3 -m json.tool | head -30

# 5. Check git commits
git log --oneline | head -10

# 6. Update status log
# Edit DEEPSEEK_STATUS_LOG.md with final summary

# 7. Create deployment checklist
# Make sure DEPLOYMENT_CHECKLIST.md is filled out
```

**If all pass → System is ready for Monday. Go rest!**

---

## 📞 Questions?

**Before asking:**
1. Check if answer is in one of the 6 documents above
2. Check if a similar passing test shows the pattern
3. Document the question in DEEPSEEK_STATUS_LOG.md

**Claude will see the log and respond.**

---

## 🚀 You've Got This

You have:
- ✅ Complete specifications
- ✅ Step-by-step instructions
- ✅ Copy-paste code fixes
- ✅ Test harness with 28 tests
- ✅ Working capital preservation rules
- ✅ 8-10 hours of work (doable)

**Result:** System ready for live trading Monday 9:30 AM with high confidence.

**Go make it happen!** 💪

---

## Document Index (All Available in /home/trading_ceo/antariksh/)

| File | Purpose | Read Time | When |
|------|---------|---|---|
| **README_DEEPSEEK_START_HERE.md** | This file | 5 min | NOW |
| **CLAUDE_MASTER_HANDOFF.md** | System state + timeline | 15 min | FIRST |
| **CRITICAL_FIXES_REQUIRED.md** | How to fix blockers | 30 min | IMMEDIATELY |
| **DEEPSEEK_EXECUTION_PLAN.md** | Task breakdown | 30 min | After reading critical |
| **DEEPSEEK_STATUS_LOG.md** | Your progress | Ongoing | Update every 2 hours |
| **PHASE_1_DEPLOYMENT_SPEC.md** | What must work | 20 min | Reference during work |
| **SCENARIO_TEST_PLAN.md** | All 32 scenarios | As needed | Reference for specific tests |
| **SCENARIO_TESTING_ANALYSIS.md** | Mocking deep dive | As needed | For architecture questions |
| **SCENARIO_COVERAGE_AND_GAPS_ANALYSIS.md** | Gap analysis | As needed | For context on what's missing |

---

**Start reading CLAUDE_MASTER_HANDOFF.md now.**

**Good luck! 🎯**

