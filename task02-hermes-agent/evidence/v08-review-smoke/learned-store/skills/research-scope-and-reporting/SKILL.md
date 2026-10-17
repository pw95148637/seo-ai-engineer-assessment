---
name: research-scope-and-reporting
description: Use when reporting research status or findings.
---

# Research scope and reporting

## Status-only requests
1. When the user requests only research budget or lessons, call `research_status` directly; do not fetch sites or run searches. A status check is not authorization to begin research.
2. Report the returned remaining request, search, off-page, and time budgets, plus tool-call usage when present. Keep the units and the distinction between requests and tool calls: a status call can count as a tool call without consuming a request.
3. Report lessons from the actual response. If the list is empty, say that no lessons were returned; do not infer procedures or findings from an empty list.
4. Present the numbers as a snapshot from that response, not a continuously current allowance. Do not save remaining budgets, run identifiers, or empty lesson lists to persistent memory because they are run-specific state.
5. Answer concisely in the user's language. If they explicitly prohibited site research, confirm that no site research was performed.

## Evidence boundary
For status reporting, use the status result as the evidence and stop once the requested fields are covered. Do not turn an administrative check into a research report or imply that any website content was verified.
