---
name: research-status-reporting
description: Use when reporting research budgets or run status.
---

# Research status reporting

1. For a status-only request, call `research_status` directly. Do not fetch websites or start searches: inspecting available capacity is not authorization to spend it on research.
2. Report the returned remaining request, search, off-page, and time budgets, keeping used counts distinct from remaining counts. Include tool-call usage when useful; do not equate tool calls with charged requests, since the counters can differ.
3. Report the returned lessons explicitly. An empty `lessons` array means no lessons were returned, not that a lookup failed.
4. Match the user's language and keep the answer compact. Round remaining seconds for readability without implying the rounded value is exact, and identify the figures as the snapshot returned by the call.
5. Keep transient counters, run IDs, and empty lesson results out of persistent memory; obtain a fresh status for the next status request.
