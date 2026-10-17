"""v8.1 role messages: v8 plus working principles for the Planner (rounds 2+). roles_v8.py stays untouched.

The only change is two Planner principles from round 2 on, written as attitudes with their reasons for the model
to think with (no if-then rules, no method, no compromise answer): weigh every comment for the reader, holding
ground with reasons or accepting what is right; and fix the problem pointed out without over- or under-correcting. The first round, the Auditor, the policy and the
controller are identical to v8, so the tiers keep MUST enforced while the Planner may hold its ground on SHOULD.
"""
import roles_v8
from roles_v8 import AUDITOR, MUST_RULE_IDS, POLICY, auditor_policy, output_schema, validate  # noqa: F401

PROMPT_VERSION = "v81"

# Working attitudes for the model to internalise, each with its reason; not an if-then checklist.
# (sentence, what it guards against)
PLANNER_PRINCIPLES = [
    ("讀者最終看到的是定稿，點擊與閱讀價值由你代表；你放棄的部分，流程中沒有其他角色會替讀者爭取。因此，Auditor 的意見，尤其是建議，是供你依自身判斷權衡的參考，而非必須執行的指令：有依據時，說明理由並維持原寫法；對方的意見正確時，就予以採納。為了讓對方滿意而讓步，或為了表現主見而反對，都不是在替讀者做判斷。",
     "v6、v8 的 Planner 對每項意見都照收，建議被當成指令；也防止反過來為反對而反對"),
    ("合規問題應確實修正，但修正的對象是被指出的問題本身。讓讀者願意點擊、讀得下去的其餘部分仍由你負責，不必因為一處被退回就把整份大綱改得保守，也不應只替換幾個字敷衍。",
     "矯枉過正（整份改保守、失去點擊）或修正不足（換字應付、下一輪再被退）"),
]


def sentences(role, state):
    parts = roles_v8.sentences(role, state)
    if role == "planner" and state["iteration"] > 1:
        # After the v8 round-2 instructions, before the traffic-demand reminder.
        at = parts.index(roles_v8.PLANNER_LATER[-1]) + 1
        parts = parts[:at] + PLANNER_PRINCIPLES + parts[at:]
    return parts


def build_messages(role, state, policy):
    messages = roles_v8.build_messages(role, state, policy)
    messages[0]["content"] = "".join(s for s, _ in sentences(role, state))
    return messages
