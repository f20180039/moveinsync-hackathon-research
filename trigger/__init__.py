"""Automated LangChain agents for the MoveInSync hackathon.

    trigger/
      common/                             shared config, data, model, Slack, state
      shift_planning_TransportManager/    Solution 1 -- daily shift planning (06:30)
      delay_management_TransportManager/  Solution 2 -- escalation & delay management

Everything outside `trigger/` is READ-ONLY to this package: it imports
`signaldesk.ingest` (the tolerant DuckDB loader) and
`signaldesk.delivery.slack_send` (the existing Slack channel) and modifies
neither.
"""
