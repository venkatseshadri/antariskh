"""Prompt: "both vega and theta positive, ATM strikes"

import os, sys, json
from pathlib import Path
from crewai import Agent, Task, Crew
from crewai.llm import LLM
from tools.contract_tools import LibrarianContractTool
from tools.ta_strategy_tools import FetchOptionChainTool, FetchGreeksTool
from crews.ta_crew import load_skill_file
from dotenv import load_dotenv


This is a contradiction test:
- Vega positive = BUY options (long = positive vega)
- Theta positive = SELL options (short = positive theta, collect time decay)

At a single ATM strike, they're OPPOSITE. The agent must identify this.
Can the agent propose a valid spread structure that reconciles both?
"""


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
    temperature=0.0,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)

librarian = Agent(
    role="Market Data Librarian (NFO Specialist)",
    goal="Resolve contracts + identify contradictions in ambiguous requests.",
    backstory=(
        "You resolve strikes into tokens. You also understand option Greeks well "
        "enough to flag impossible requests. Vega-positive = buy, Theta-positive = sell — "
        "they are opposite at a single strike. You know that a spread structure "
        "(e.g., Iron Butterfly: sell body + buy wings, or calendar spread: sell near "
        "+ buy far) can balance them."
    ),
    tools=[
        LibrarianContractTool(),
        FetchOptionChainTool(),
        FetchGreeksTool(),
        load_skill_file,
    ],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

task = Task(
    description=(
        "A user says: 'both vega and theta positive, ATM strikes.'\n\n"
        "Your job as the Market Data Librarian:\n\n"
        "1. First, recognize the contradiction: at a single strike, vega-positive "
        "(BUY) and theta-positive (SELL) are OPPOSITE. You cannot buy AND sell "
        "the same option.\n\n"
        "2. Call load_skill_file('strategy-architect.json') to check the playbook "
        "for any strategy that can achieve net-positive vega AND net-positive theta "
        "simultaneously via a spread (not a single option).\n\n"
        "3. If no such strategy exists, state clearly that it's impossible at a single "
        "ATM strike and explain why.\n\n"
        "4. If a strategy DOES exist (e.g., Iron Butterfly body = theta+, wings = vega+), "
        "resolve BOTH the ATM SELL legs AND the OTM BUY wings using "
        "contract_librarian_lookup.\n\n"
        "5. Call fetch_greeks_from_duck_db to verify the current net Greeks support "
        "this structure."
    ),
    expected_output=(
        "Either: an explicit 'IMPOSSIBLE' response explaining the contradiction, "
        "OR: a spread structure with both net vega and net theta positive, "
        "with all legs resolved via contract_librarian_lookup."
    ),
    agent=librarian,
)

print("\n" + "=" * 60)
print("PROMPT: 'both vega and theta positive, ATM strikes'")
print("=" * 60)

crew = Crew(agents=[librarian], tasks=[task], memory=False)
result = crew.kickoff()

print("\n*** FINAL ANSWER ***")
print(result)
