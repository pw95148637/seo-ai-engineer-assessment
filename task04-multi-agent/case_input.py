"""Versioned task inputs, independent of a model/provider."""
import json
from pathlib import Path
from workflow import State
def load_case(name, mode, policy_version):
    if name not in ("normal","forced_conflict","immutable"):
        raise ValueError("Unknown case")
    case=json.loads(Path(__file__).with_name("cases").joinpath(name+".json").read_text(encoding="utf-8"))
    state=State(request=case["request"],initial_instruction=case["initial_instruction"],
                scenario=case["id"],immutable_conflict=case["immutable_conflict"],
                max_iterations=case["max_iterations"],mode=mode,policy_version=policy_version)
    return case,state
