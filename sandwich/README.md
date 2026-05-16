# Sandwich

Entry-signal research project. Produces probabilistic directional/path signals for downstream credit-spread strategies.

## Status

Step 1: Connect & Inspect — in progress.

## Layout

- `steps/` — one standalone `.py` script per step, numbered
- (other folders added as the project earns them)

## How to run

Each step is a standalone Python script. From the repo root:

    python -m sandwich.steps.step01_connect_and_inspect

Or directly:

    python sandwich/steps/step01_connect_and_inspect.py

## Rules

- Sandwich code lives only inside `antariksh/sandwich/`.
- Sandwich does not import from or modify existing antariksh code.
- Each step is a single `.py` script with strict acceptance criteria.
- No Jupyter notebooks. Standalone scripts only.
- New steps are not started until the previous step is reported back and acknowledged.

## Steps log

- Step 1: Connect & Inspect — `steps/step01_connect_and_inspect.py`
