"""
NexVigilant Station + LangChain Integration Example
====================================================

NexVigilant Station (mcp.nexvigilant.com) is a pharmacovigilance MCP server
providing 2,023 tools for drug safety intelligence. No authentication required.
CORS enabled. Three transports: Streamable HTTP, SSE, and REST.

This example connects a LangChain agent to NexVigilant Station via MCP SSE
transport and queries adverse reactions for metformin.

Requirements:
    pip install langchain-mcp-adapters langchain-anthropic langgraph

Usage:
    export ANTHROPIC_API_KEY="your-key-here"
    python langchain-nexvigilant.py
"""

import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

# ---------------------------------------------------------------------------
# 1. NexVigilant Station configuration
# ---------------------------------------------------------------------------
# Primary endpoint (Cloud Run, auto-scaling):
STATION_SSE_URL = "https://mcp.nexvigilant.com/sse"

# Zero-cold-start alternative (always warm, slightly higher latency):
# STATION_SSE_URL = "https://station.nexvigilant.com/sse"

# NexVigilant Station requires no API key or authentication.


async def main():
    # ------------------------------------------------------------------
    # 2. Connect to NexVigilant Station via SSE and create tools
    # ------------------------------------------------------------------
    print("Connecting to NexVigilant Station via SSE...")

    async with MultiServerMCPClient(
        {
            "nexvigilant": {
                "url": STATION_SSE_URL,
                "transport": "sse",
            }
        }
    ) as client:
        # Get all tools from the Station
        tools = client.get_tools()
        print(f"Loaded {len(tools)} tools from NexVigilant Station")

        # Optional: list some tool names to see what is available
        # tool_names = [t.name for t in tools]
        # print("Sample tools:", tool_names[:15])

        # --------------------------------------------------------------
        # 3. Create the LLM and agent
        # --------------------------------------------------------------
        # Using Claude as the reasoning model. You can substitute any
        # LangChain-compatible LLM (OpenAI, etc).
        model = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            temperature=0,
        )

        # Create a ReAct agent with access to all Station tools.
        # The agent will autonomously decide which tools to call based
        # on the user's question.
        agent = create_react_agent(
            model=model,
            tools=tools,
        )

        # --------------------------------------------------------------
        # 4. Run a drug safety query
        # --------------------------------------------------------------
        query = (
            "What are the adverse reactions for metformin? "
            "Start by calling nexvigilant_chart_course with "
            "course='drug-safety-profile' to get the recommended workflow, "
            "then follow the steps to search FAERS and check DailyMed labeling."
        )

        print(f"\nQuery: {query}\n")
        print("Running agent...\n")

        # Stream the agent's reasoning and tool calls
        async for chunk in agent.astream(
            {"messages": [{"role": "user", "content": query}]},
        ):
            # Print agent messages as they arrive
            if "agent" in chunk:
                for msg in chunk["agent"]["messages"]:
                    if hasattr(msg, "content") and msg.content:
                        print(f"Agent: {msg.content}\n")
            elif "tools" in chunk:
                for msg in chunk["tools"]["messages"]:
                    print(f"Tool [{msg.name}]: {str(msg.content)[:200]}...\n")


# ---------------------------------------------------------------------------
# Alternative: Direct REST API usage (no MCP client needed)
# ---------------------------------------------------------------------------
# NexVigilant Station also exposes a REST API for simpler integrations:
#
#   import requests
#
#   # List all available tools
#   tools = requests.get("https://mcp.nexvigilant.com/tools").json()
#   print(f"{len(tools)} tools available")
#
#   # Call a specific tool via JSON-RPC
#   response = requests.post(
#       "https://mcp.nexvigilant.com/rpc",
#       json={
#           "jsonrpc": "2.0",
#           "method": "tools/call",
#           "params": {
#               "name": "nexvigilant_chart_course",
#               "arguments": {"course": "drug-safety-profile"},
#           },
#           "id": 1,
#       },
#   )
#   print(response.json())


if __name__ == "__main__":
    asyncio.run(main())
