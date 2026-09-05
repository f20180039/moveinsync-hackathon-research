"""Shared plumbing for every agent under `trigger/`: configuration, the data
connection, the LangChain model factory, Slack delivery and the lightweight
dedup state. Agent-specific logic lives in the agent's own folder."""
