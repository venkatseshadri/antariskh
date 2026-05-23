"""Architect theory test — Iron Condor structure + Delta rule from skill file."""

import os, sys
from pathlib import Path
from crewai import Agent, Task, Crew
from crewai.llm import LLM
from crews.ta_crew import strategy_architect as _architect, load_skill_file
from dotenv import load_dotenv



env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().split("\n"):
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", ds_key)
os.environ.setdefault(
    "OPENAI_BASE_URL",
    os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
)

sys.path.insert(0, str(Path(__file__).parent.parent))


ds_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.1,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)

varaha_architect = Agent(
    role=_architect.role,
    goal=_architect.goal,
    backstory=_architect.backstory,
    tools=[load_skill_file],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

# --- TEST 1: The "Iron Condor" Theory Test ---

task_iron_condor = Task(
    description=(
        "I need to understand our options strategies. "
        "Call load_skill_file('strategy-architect.json') to read the playbook. "
        "How many spreads make up an Iron Condor, and according to our rules, "
        "what Delta should the sell options usually be targeted at?"
    ),
    expected_output="A brief explanation of the Iron Condor structure and the Delta rule.",
    agent=varaha_architect,
)

# --- TEST 3: Risk Parameter Logic ---
task_risk = Task(
    description=(
        "Call load_skill_file('strategy-architect.json') to read the playbook. "
        "What is the maximum loss possible in an Iron Condor according to our "
        "internal strategy definitions? How do wings limit the maximum loss?"
    ),
    expected_output="An explanation of how wings limit the maximum loss in an Iron Condor.",
    agent=varaha_architect,
)

# --- TEST 4: Strategy Identification ---
task_structure = Task(
    description=(
        "Call load_skill_file('strategy-architect.json') to read the playbook. "
        "Identify the strategy that has two sell strikes at the same strike "
        "(one PE and one CE) and two buy strikes serving as hedges. "
        "What is the name of this strategy WITHOUT the hedges?"
    ),
    expected_output="The name of the strategy (Iron Butterfly) and its unhedged version (Short Straddle).",
    agent=varaha_architect,
)

# --- TEST 5: Delta-Neutral Strategies ---
task_delta_neutral = Task(
    description=(
        "Call load_skill_file('strategy-architect.json') to read the playbook. "
        "Name all the delta-neutral options strategies defined in our internal "
        "playbook. For each one, explain briefly why it is delta-neutral."
    ),
    expected_output="List of delta-neutral strategies with rationale for each.",
    agent=varaha_architect,
)

# --- TEST 6: Asymmetric Iron Fly Wings ---
task_asymmetric_fly = Task(
    description=(
        "Call load_skill_file('strategy-architect.json') to read the playbook. "
        "Consider an Iron Butterfly: sell ATM Call + sell ATM Put, protected by "
        "long OTM wings. What happens if one of the hedges (say the call wing) is "
        "placed CLOSER to the centre/sell strikes than the other side (the put wing)? "
        "How does this affect the risk profile, Delta, and P&L asymmetry?"
    ),
    expected_output="Explanation of asymmetric Iron Fly risk: Delta tilt, P&L skew, which side is naked.",
    agent=varaha_architect,
)

# --- TEST 7: Unbalanced Iron Condor (Ratio Wings) ---
task_unbalanced_condor = Task(
    description=(
        "Call load_skill_file('strategy-architect.json') to read the playbook. "
        "Consider an Iron Condor. Normally it has one Bull Put spread and one Bear "
        "Call spread. Now imagine we sell TWO Bear Call spreads and only ONE Bull "
        "Put spread. What happens to the risk profile? Which direction becomes "
        "more dangerous, and why?"
    ),
    expected_output="Explanation of unbalanced condor: directional Delta, asymmetric risk, margin impact.",
    agent=varaha_architect,
)

# --- TEST 8: Calendar Spread / Theta Greek ---
task_theta_calendar = Task(
    description=(
        "Call load_skill_file('strategy-architect.json') to read the playbook. "
        "Consider this trade: you SELL this week's NIFTY option and BUY next week's "
        "NIFTY option at the same strike. Which Greek parameter is primarily at play "
        "here, and why? Explain how this trade profits and what risks it faces."
    ),
    expected_output="Identification of Theta as the primary Greek, with calendar spread explanation.",
    agent=varaha_architect,
)

if __name__ == "__main__":
    tests = [
        ("TEST 1: Iron Condor Structure & Delta Rule", task_iron_condor),
        ("TEST 3: Iron Condor Max Loss / Risk Definition", task_risk),
        ("TEST 4: Strategy Structural Mapping", task_structure),
        ("TEST 5: Delta-Neutral Strategies", task_delta_neutral),
        ("TEST 6: Asymmetric Iron Fly Wings", task_asymmetric_fly),
        ("TEST 7: Unbalanced Iron Condor (Ratio Wings)", task_unbalanced_condor),
        ("TEST 8: Calendar Spread / Theta Greek", task_theta_calendar),
    ]
    for label, task in tests:
        print("\n" + "=" * 60)
        print(label)
        print("=" * 60)
        crew = Crew(agents=[varaha_architect], tasks=[task], memory=False)
        print(crew.kickoff())

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60)
    crew_test = Crew(agents=[varaha_architect], tasks=[task_iron_condor], memory=False)
    print(crew_test.kickoff())

    print("\n" + "=" * 60)
    print("TEST 3: Iron Condor Max Loss / Risk Definition")
    print("=" * 60)
    crew_risk = Crew(agents=[varaha_architect], tasks=[task_risk], memory=False)
    print(crew_risk.kickoff())

    print("\n" + "=" * 60)
    print("TEST 4: Strategy Structural Mapping")
    print("=" * 60)
    crew_structure = Crew(
        agents=[varaha_architect], tasks=[task_structure], memory=False
    )
    print(crew_structure.kickoff())

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60)
