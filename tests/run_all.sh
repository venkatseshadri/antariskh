#!/bin/bash
# Run all 32 scenarios, generate SCENARIO_TEST_RESULTS.md
set -u
cd /home/trading_ceo/antariksh

export ANTARIKSH_MOCK_MODE=1
export PYTHONPATH="/home/trading_ceo/antariksh:$PYTHONPATH"

python3 -m pytest tests/test_scenarios.py \
    --tb=short \
    --json-report --json-report-file=tests/results.json \
    -v 2>&1 | tee tests/run.log

# Generate the markdown report
python3 tests/generate_report.py tests/results.json > SCENARIO_TEST_RESULTS.md
echo "Report written to SCENARIO_TEST_RESULTS.md"
