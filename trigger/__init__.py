"""Solution 1 -- Transport Manager: automated daily shift planning.

Self-contained package. Everything outside `trigger/` is READ-ONLY to this
code: it imports `signaldesk.ingest` (the tolerant DuckDB loader) and
`signaldesk.delivery.slack_send` (the existing Slack channel) and modifies
neither.
"""
