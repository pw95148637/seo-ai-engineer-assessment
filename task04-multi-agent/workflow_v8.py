"""Tiered controller (v8): only MUST items send a draft back; SHOULD suggestions never cost a round.

workflow.py (v6, v7) stays untouched so earlier evidence remains reproducible; this module reuses its State,
snapshot, emit and error types. The decision is computed here from rule IDs and code checks, never from a level
or verdict written by a model:
- program_findings: the two literal terms anywhere in the outline, and the guarantee words CLAIMS lists for titles
  and headings, checked in code before the Auditor runs (MUST, rule CLAIMS).
- review.must: program findings plus every Auditor finding (each cites a MUST rule ID from the policy).
- review.should: at most `suggestions.max` Auditor suggestions; the Planner adopts or declines each with a reason.
- blocked = bool(review.must). Not blocked ends the loop at once and attaches the suggestions the Planner declined,
  never answered, or never saw (raised in the final round) to the final outline for the human editor.
"""
import asyncio
import copy
import random
from dataclasses import dataclass, field
from workflow import ProviderError, State, TransientError, emit, snapshot

SUGGESTION_ACTIONS = ("adopt", "decline")


@dataclass
class TieredState(State):
    policy_version: str = "custom-provisional-v5-tiered"
    program_findings: list = field(default_factory=list)  # code checks on the current draft (MUST)
    review: dict = field(default_factory=dict)            # {"blocked", "must": [...], "should": [...], "note"}
    suggestions: list = field(default_factory=list)       # SHOULD ledger across rounds, with the Planner's answers


def must_rule_ids(policy):
    return tuple(r["id"] for r in policy["rules"] if r["level"] == "MUST")


def section_lines(section):
    """(heading, points) of a v8 section; a plain v6 string counts as points only."""
    if isinstance(section, str):
        return "", section
    return section.get("heading", ""), section.get("points", "")


def split_v6_section(text):
    """Registered split rule for v6 string sections: first "——", else first "："; else all heading. No text added."""
    for sep in ("——", "："):
        if sep in text:
            heading, points = text.split(sep, 1)
            return {"heading": heading, "points": points}
    return {"heading": text, "points": ""}


def flatten(section):
    heading, points = section_lines(section)
    return "：".join(x for x in (heading, points) if x)


def validate(role, result, policy):
    if not isinstance(result, dict):
        raise ValueError("Response must be object")
    if role == "planner":
        if not isinstance(result.get("title"), str) or not result["title"].strip():
            raise ValueError("Missing title")
        sections = result.get("sections")
        if not isinstance(sections, list) or not sections or not all(
                isinstance(x, dict) and isinstance(x.get("heading"), str) and x["heading"].strip()
                and isinstance(x.get("points", ""), str) for x in sections):
            raise ValueError("Invalid sections")
        if not isinstance(result.get("negotiation_note", ""), str):
            raise ValueError("Invalid negotiation note")
        responses = result.get("suggestion_responses", [])
        if not isinstance(responses, list) or not all(
                isinstance(x, dict) and isinstance(x.get("id"), str) and x.get("action") in SUGGESTION_ACTIONS
                and isinstance(x.get("reason", ""), str) for x in responses):
            raise ValueError("Invalid suggestion responses")
    elif role == "auditor":
        findings, suggestions = result.get("findings"), result.get("suggestions", [])
        if not isinstance(result.get("note", ""), str):
            raise ValueError("Invalid note")
        if not isinstance(findings, list):
            raise ValueError("Invalid findings")
        ids = must_rule_ids(policy)
        for f in findings:
            # An omission (e.g. no legal-risk disclosure) has no sentence to quote; it still blocks (fail closed).
            if not isinstance(f, dict) or not isinstance(f.get("quote"), str) or not all(
                    isinstance(f.get(k), str) and f[k].strip() for k in ("reason", "revision", "rule")):
                raise ValueError("Incomplete finding")
            if f["rule"] not in ids:
                raise ValueError("Finding cites a rule that is not a MUST rule: " + f["rule"])
        if not isinstance(suggestions, list) or not all(isinstance(x, str) and x.strip() for x in suggestions):
            raise ValueError("Invalid suggestions")
    else:
        raise ValueError("Unknown role")


def program_findings(draft, policy):
    """Mechanical MUST checks; one finding per (term, line). Headings and the title only for heading terms."""
    checks = policy["program_checks"]
    title = draft.get("title", "")
    headings = [section_lines(s)[0] for s in draft.get("sections", [])]
    points = [section_lines(s)[1] for s in draft.get("sections", [])]
    out = []
    literal, heading_terms = checks["literal_guard_terms"], checks["heading_guarantee_terms"]
    for term in literal["terms"]:
        for line in [title] + headings + points:
            if line and term in line:
                out.append({"quote": line, "rule": literal["rule"], "source": "program", "term": term,
                            "reason": f"含零容忍詞彙「{term}」；規則禁止此詞出現在標題與大綱，引號、疑問或拆穿語境也不例外",
                            "revision": "刪除此詞，改用不含此詞的說法表達同一重點"})
    for term in heading_terms["terms"]:
        for line in [title] + headings:
            if line and term in line:
                out.append({"quote": line, "rule": heading_terms["rule"], "source": "program", "term": term,
                            "reason": f"標題或小標含保證式說法「{term}」；搜尋結果與目錄常只顯示標題或小標，"
                                      "讀者可能只看到保證字眼與娛樂城並列",
                            "revision": "從標題或小標移除此說法；拆解話術時只在內容要點描述，並標明是廣告說法"})
    return out


def derive_review(iteration, program, audit, policy):
    """The controller's decision input: levels come from the rule ID and the field, never from the model."""
    limit = policy["suggestions"]["max"]
    must = [{"id": f"M{iteration}-{k}", **f} for k, f in enumerate(
        list(program) + [{"quote": f["quote"], "rule": f["rule"], "source": "auditor", "reason": f["reason"],
                          "revision": f["revision"]} for f in audit["findings"]], 1)]
    should = [{"id": f"S{iteration}-{k}", "suggestion": x}
              for k, x in enumerate(audit.get("suggestions", [])[:limit], 1)]
    return {"blocked": bool(must), "must": must, "should": should, "note": audit.get("note", "")}


def answer_suggestions(ledger, draft):
    """Record the Planner's adopt/decline for every open suggestion; silence is recorded as unanswered."""
    answers = {r["id"]: r for r in draft.get("suggestion_responses", [])}
    for item in ledger:
        if item["status"] != "open":
            continue
        answer = answers.get(item["id"])
        if answer is None:
            item["status"] = "unanswered"
        else:
            item["status"] = "adopted" if answer["action"] == "adopt" else "declined"
            item["planner_reason"] = answer.get("reason", "")


def attached(ledger):
    """Suggestions the final carries for the human editor: everything not adopted, with the Planner's reason."""
    return [copy.deepcopy(x) for x in ledger if x["status"] != "adopted"]


async def call(agent, role, s, timeout, retries, backoff, sink, policy):
    for attempt in range(retries + 1):
        context = snapshot(s)
        try:
            result = await asyncio.wait_for(agent(role, context), timeout)
            validate(role, result, policy)
            emit(s, {"node": role, "iteration": s.iteration, "attempt": attempt,
                     "input": context, "output": result}, sink)
            return result
        except (TransientError, TimeoutError) as e:
            error = {"role": role, "attempt": attempt, "iteration": s.iteration, "type": type(e).__name__}
            s.errors.append(error)
            if sink: sink({"run_id": s.run_id, "mode": s.mode, "node": "call_error", **error})
            if attempt == retries:
                raise
            delay = getattr(e, "retry_after", None)
            if delay is None:
                delay = backoff * 2 ** attempt * random.uniform(.8, 1.2)
            await asyncio.sleep(delay)


async def run(agent, s=None, policy=None, timeout=30, retries=1, total_timeout=180, backoff=.5, sink=None):
    s = s or TieredState()
    if policy is None or "program_checks" not in policy:
        raise ValueError("The tiered controller needs a tiered policy")
    if s.mode not in ("offline_fixture", "offline_http_fixture", "llm_runtime"):
        raise ValueError("Unknown mode")
    if s.max_iterations < 1 or retries < 0 or timeout <= 0 or total_timeout <= 0 or backoff < 0:
        raise ValueError("Invalid bounds")
    if s.status != "running":
        raise ValueError("A completed State cannot be rerun")
    try:
        async with asyncio.timeout(total_timeout):
            for i in range(1, s.max_iterations + 1):
                s.iteration = i
                s.draft = await call(agent, "planner", s, timeout, retries, backoff, sink, policy)
                answer_suggestions(s.suggestions, s.draft)
                s.program_findings = program_findings(s.draft, policy)
                emit(s, {"node": "program_check", "iteration": i, "output": s.program_findings}, sink)
                s.audit = await call(agent, "auditor", s, timeout, retries, backoff, sink, policy)
                s.review = derive_review(i, s.program_findings, s.audit, policy)
                s.suggestions += [{"round": i, **x, "status": "open"} for x in s.review["should"]]
                if s.immutable_conflict:
                    s.status = "unsatisfiable"
                    emit(s, {"node": "decision", "iteration": i, "action": "unsatisfiable",
                             "reason": "保證措辭與禁止保證均為硬限制，不能同時滿足", "review": s.review}, sink)
                    break
                if not s.review["blocked"]:
                    s.status = "approved_provisional"
                    s.final = {**copy.deepcopy(s.draft), "attached_suggestions": attached(s.suggestions)}
                    emit(s, {"node": "decision", "iteration": i, "action": "approve_provisional",
                             "review": s.review}, sink)
                    break
                emit(s, {"node": "decision", "iteration": i,
                         "action": "revise" if i < s.max_iterations else "human_review", "review": s.review}, sink)
            else:
                s.status = "human_review"
    except (TransientError, ProviderError, TimeoutError, ValueError) as e:
        s.status = "error"
        s.errors.append({"type": type(e).__name__, "message": str(e)})
    finally:
        if sink:
            sink({"run_id": s.run_id, "mode": s.mode, "node": "finish", "status": s.status,
                  "iteration": s.iteration, "errors": s.errors})
    return s
