"""
NexVigilant Station + CrewAI Integration Example
=================================================

NexVigilant Station (mcp.nexvigilant.com) is a pharmacovigilance MCP server
providing 2,023 tools for drug safety intelligence. No authentication required.
CORS enabled. Three transports: Streamable HTTP, SSE, and REST.

This example connects a CrewAI agent to NexVigilant Station via MCP and runs
a pharmacovigilance signal investigation for semaglutide + pancreatitis.

Requirements:
    pip install crewai crewai-tools mcp

Usage:
    export ANTHROPIC_API_KEY="your-key-here"  # or OPENAI_API_KEY
    python crewai-nexvigilant.py
"""

import asyncio
import json
from crewai import Agent, Task, Crew, Process
from crewai.tools import MCPServerAdapter

# ---------------------------------------------------------------------------
# 1. Configure the MCP connection to NexVigilant Station
# ---------------------------------------------------------------------------
# Primary endpoint (Cloud Run, auto-scaling):
STATION_URL = "https://mcp.nexvigilant.com/sse"

# Zero-cold-start alternative (always warm, slightly higher latency):
# STATION_URL = "https://station.nexvigilant.com/sse"

# NexVigilant Station requires no API key or authentication.


async def main():
    # ------------------------------------------------------------------
    # 2. Connect to NexVigilant Station and load tools
    # ------------------------------------------------------------------
    print("Connecting to NexVigilant Station...")
    adapter = MCPServerAdapter(
        server_params={
            "url": STATION_URL,
        }
    )

    # Load all available tools from the Station.
    # The Station exposes 2,023 tools across pharmacovigilance, regulatory
    # intelligence, clinical trials, epidemiology, and more.
    tools = adapter.tools()
    print(f"Loaded {len(tools)} tools from NexVigilant Station")

    # Optional: inspect available tool names
    # for tool in tools[:20]:
    #     print(f"  - {tool.name}")

    # ------------------------------------------------------------------
    # 3. Create a PV Signal Investigator agent
    # ------------------------------------------------------------------
    investigator = Agent(
        role="PV Signal Investigator",
        goal=(
            "Investigate pharmacovigilance safety signals by querying FDA FAERS, "
            "computing disproportionality metrics (PRR, ROR, IC, EBGM), checking "
            "drug labeling, and searching published literature."
        ),
        backstory=(
            "You are a pharmacovigilance scientist with expertise in signal "
            "detection and causality assessment. You use NexVigilant Station "
            "tools to access real-time safety data from FDA, EMA, WHO, and "
            "published literature. Always start by calling nexvigilant_chart_course "
            "to get the recommended workflow for any investigation."
        ),
        tools=tools,
        verbose=True,
    )

    # ------------------------------------------------------------------
    # 4. Define the investigation task
    # ------------------------------------------------------------------
    investigation = Task(
        description="""
        Investigate the safety signal for semaglutide and pancreatitis.

        Follow this workflow:
        1. Call nexvigilant_chart_course with course="signal-investigation"
           to get the step-by-step investigation protocol.
        2. Search FAERS for adverse event reports of semaglutide + pancreatitis.
        3. Compute disproportionality metrics (PRR and ROR at minimum).
        4. Check DailyMed labeling for semaglutide to see if pancreatitis
           is already listed as a known adverse reaction.
        5. Search PubMed for case reports of semaglutide-associated pancreatitis.
        6. Summarize findings with a signal assessment verdict.

        Present results as a structured safety signal report.
        """,
        expected_output=(
            "A structured PV signal report containing: FAERS case counts, "
            "disproportionality metrics (PRR, ROR with confidence intervals), "
            "labeling status, literature evidence, and an overall signal "
            "assessment verdict (confirmed/potential/refuted)."
        ),
        agent=investigator,
    )

    # ------------------------------------------------------------------
    # 5. Assemble and run the crew
    # ------------------------------------------------------------------
    crew = Crew(
        agents=[investigator],
        tasks=[investigation],
        process=Process.sequential,
        verbose=True,
    )

    print("\nStarting signal investigation for semaglutide + pancreatitis...\n")
    result = crew.kickoff()

    print("\n" + "=" * 70)
    print("SIGNAL INVESTIGATION REPORT")
    print("=" * 70)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
