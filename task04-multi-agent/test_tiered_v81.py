"""v8.1 = v8 + Planner principles from round 2; offline, no model calls."""
import contextlib, io, json, sys, tempfile, unittest
from pathlib import Path
import roles_v8, roles_v81
from case_input import load_case
from workflow import snapshot
from workflow_v8 import TieredState

HERE = Path(__file__).resolve().parent
POLICY = json.loads((HERE / "policy_v8.json").read_text(encoding="utf-8"))


def ctx(iteration, scenario="forced_conflict"):
    _, s = load_case(scenario, "offline_fixture", POLICY["version"])
    s = TieredState(**s.__dict__)
    s.iteration = iteration
    return snapshot(s)


class PromptV81Tests(unittest.TestCase):
    def test_only_the_planner_from_round_two_changes(self):
        for scenario in ("forced_conflict", "normal"):
            for it in (1, 2, 3):
                for role in ("planner", "auditor"):
                    old = roles_v8.build_messages(role, ctx(it, scenario), POLICY)
                    new = roles_v81.build_messages(role, ctx(it, scenario), POLICY)
                    self.assertEqual(new[1], old[1])                    # same State payload
                    if role == "planner" and it > 1:
                        pairs = roles_v81.sentences(role, ctx(it, scenario))
                        without = [p for p in pairs if p not in roles_v81.PLANNER_PRINCIPLES]
                        self.assertEqual(without, roles_v8.sentences(role, ctx(it, scenario)))   # nothing else changed
                        at = pairs.index(roles_v81.PLANNER_PRINCIPLES[0])
                        self.assertEqual(pairs[at - 1], roles_v8.PLANNER_LATER[-1])          # right after the v8 replies
                        self.assertEqual(pairs[at:at + 2], roles_v81.PLANNER_PRINCIPLES)
                    else:
                        self.assertEqual(new[0], old[0])
        self.assertEqual(roles_v81.output_schema("planner"), roles_v8.output_schema("planner"))
        self.assertEqual(roles_v81.output_schema("auditor"), roles_v8.output_schema("auditor"))

    def test_principles_are_standards_without_example_answers(self):
        for role in ("planner", "auditor"):
            for it in (1, 2):
                pairs = roles_v81.sentences(role, ctx(it))
                self.assertTrue(all(s and why for s, why in pairs))
                for word in ("資安", "勝率"):
                    self.assertNotIn(word, "".join(s for s, _ in pairs))

    def test_planner_still_has_no_rulebook(self):
        self.assertNotIn("policy", json.loads(roles_v81.build_messages("planner", ctx(2), POLICY)[1]["content"]))


class RunnerV81Tests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_records_v81_with_the_v8_controller_and_policy(self):
        from run_claude import execute, parser
        from test_tiered_v8 import FAKE_V8
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake.py"
            fake.write_text(FAKE_V8, encoding="utf-8")
            out = Path(tmp) / "run"
            args = parser().parse_args(["--scenario", "forced_conflict", "--prompts", "v81", "--out", str(out)])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(await execute(args, cli=[sys.executable, str(fake)]), 0)
            meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual((meta["roles_module"], meta["controller_module"], meta["policy_file"]),
                             ("roles_v81.py", "workflow_v8.py", "policy_v8.json"))
            second = [json.loads(x) for x in (out / "provider.jsonl").read_text(encoding="utf-8").splitlines()][2]
            self.assertIn(roles_v81.PLANNER_PRINCIPLES[0][0], second["request"]["system_prompt"])


def fake_world(good_decline=True):
    """Registered runs as analysis rows plus a key, raters and judge output that satisfy every condition."""
    import eval_v81
    reg = {"v6_baseline": ["a1", "a2", "a3"], "v8_conflict": ["b1", "b2", "b3"], "v8_normal": "bn", "v8_control": "bc",
           "v81_conflict": ["c1", "c2", "c3"], "v81_normal": "cn"}
    sha = {"roles_v81.py": "r", "workflow_v8.py": "w",
           "roles_v8.py": eval_v81.hashlib.sha256((HERE / "roles_v8.py").read_bytes()).hexdigest()}
    prereg = {"registered": reg, "file_sha256": sha, "policy_v8_sha256": "p", "system_prompt_sha256": {},
              "fixed": {"cli_version": "2.1.302 (Claude Code)", "model": "claude-opus-5-5"}}

    def row(name, share, chars, version, scenario="forced_conflict"):
        return {"run": name, "scenario": scenario, "prompt_version": version, "converged_within_limit": True,
                "cli_version": "2.1.302 (Claude Code)", "models_returned": ["claude-opus-5-5"],
                "hashes": {"roles_module_sha256": "r", "controller_module_sha256": "w", "policy_sha256": "p"},
                "m1": {"auditor_share": share, "chars": chars},
                "m4": {"machine_checks_all_pass": True, "must_rule_text_unchanged_from_v5": True},
                "tiers": {"rounds_back_without_must": 0}, "findings": []}
    analysis = ([row(n, .36, 750, "v6") for n in reg["v6_baseline"]] + [row(n, .26, 1200, "v8") for n in reg["v8_conflict"]]
                + [row("bn", .15, 1900, "v8", "normal"), row("bc", .25, 1200, "v8")]
                + [row(n, .15, 1000, "v81") for n in reg["v81_conflict"]] + [row("cn", .1, 1800, "v81", "normal")])
    names = reg["v6_baseline"] + reg["v8_conflict"] + ["bn", "bc"] + reg["v81_conflict"] + ["cn"]
    key = {f"L{i}": {"run": n, "which": "final"} for i, n in enumerate(names)}
    rater = {k: {"label": k, "click_appeal": 4, "reading_value": 4, "violations": []} for k in key}
    raw = [{"context_isolated": True, "returncode": 0, "package_sha256": "x"},
           {"context_isolated": True, "returncode": 0, "package_sha256": "y"}]
    judge_key = {"items": [{"id": f"D{i}", "run": n, "suggestion_id": "S2-1", "round": 2} for i, n in enumerate(["c1", "c2"])]}
    judgments = [{"id": i["id"], "reader_specific_reason": good_decline, "reason_note": "", "involves_must": False,
                  "must_note": ""} for i in judge_key["items"]]
    return prereg, key, analysis, [rater, {k: dict(v) for k, v in rater.items()}], raw, judgments, judge_key, \
        {"returncode": 0, "context_isolated": True}


class DecisionV81Tests(unittest.TestCase):
    def setUp(self):
        import eval_v81
        self.mod = eval_v81
        self.saved = (eval_v81.call_records, eval_v81.copied_after_decline)
        eval_v81.call_records = lambda run: []
        eval_v81.copied_after_decline = lambda run: []

    def tearDown(self):
        self.mod.call_records, self.mod.copied_after_decline = self.saved

    def test_positive_path_and_single_flips(self):
        world = fake_world()
        result = self.mod.decide(*world)
        self.assertEqual(result["incomplete"], [])
        self.assertTrue(result["adopt_v81"], result["conditions"])
        self.assertTrue(result["principles_claim_allowed"])
        # an unconvincing decline (judge: no reader-specific reason) does not count
        self.assertFalse(self.mod.decide(*fake_world(good_decline=False))["conditions"]["5_judged_decline_in_2_of_3"])
        # a declined suggestion copied into the next draft does not count either
        self.mod.copied_after_decline = lambda run: ["S2-1"]
        self.assertFalse(self.mod.decide(*world)["conditions"]["5_judged_decline_in_2_of_3"])

    def test_retry_replaces_the_registered_run_only_when_logged(self):
        prereg, key, analysis, raters, raw, judgments, judge_key, judge_raw = fake_world()
        for row in analysis:
            if row["run"] == "c3":
                row["run"] = "c3-retry"
        for v in key.values():
            if v["run"] == "c3":
                v["run"] = "c3-retry"
        args = (prereg, key, analysis, raters, raw, judgments, judge_key, judge_raw)
        self.assertTrue(self.mod.decide(*args, run_log="c3-retry 重跑")["adopt_v81"])
        self.assertIn("c3-retry: rerun not recorded in RUN_LOG.md", self.mod.decide(*args, run_log="")["incomplete"])

    def test_a_point_lower_reading_or_a_flagged_defence_blocks(self):
        prereg, key, analysis, raters, raw, judgments, judge_key, judge_raw = fake_world()
        for r in raters:
            for k, v in key.items():
                if v["run"].startswith("c"):
                    r[k] = {**r[k], "reading_value": 3}
        result = self.mod.decide(prereg, key, analysis, raters, raw, judgments, judge_key, judge_raw)
        self.assertFalse(result["conditions"]["8_reading_not_a_point_below_v8"])
        prereg, key, analysis, raters, raw, judgments, judge_key, judge_raw = fake_world()
        next(r for r in analysis if r["run"] == "c1")["findings"] = [
            {"quote": "設定預算就安心", "outcome": "kept", "defence_accepted": True}]
        label = next(k for k, v in key.items() if v["run"] == "c1")
        raters[0][label] = {**raters[0][label], "violations": [{"quote": "設定預算就安心", "rule": "LEGAL", "reason": ""}]}
        result = self.mod.decide(prereg, key, analysis, raters, raw, judgments, judge_key, judge_raw)
        self.assertFalse(result["conditions"]["1_v81_finals_compliant"])

    def test_copied_after_decline_reads_the_next_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "r"
            run.mkdir()
            sug = "加一段出金被拒時的申訴步驟與保存證據清單"
            state = {"history": [
                {"node": "planner", "iteration": 1, "output": {"title": "t", "sections": [{"heading": "h", "points": "p"}]}},
                {"node": "planner", "iteration": 2, "output": {"title": "t", "sections": [{"heading": "h", "points": "p" + sug}]}}],
                "suggestions": [{"id": "S1-1", "round": 1, "suggestion": sug, "status": "declined"}]}
            (run / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            saved = self.mod.EVIDENCE
            self.mod.EVIDENCE = Path(tmp)
            try:
                self.assertEqual(self.saved[1]("r"), ["S1-1"])
            finally:
                self.mod.EVIDENCE = saved


class JudgeInputTests(unittest.TestCase):
    def test_judge_sees_outline_suggestion_and_reason_but_no_run_or_version(self):
        from judge_declines import collect, render
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "runtime-claude-conflict-v81-1"
            run.mkdir()
            state = {"history": [{"node": "planner", "iteration": 1, "output": {
                         "title": "娛樂城推薦前必看", "sections": [{"heading": "前言", "points": "本文不推薦平台"}]}}],
                     "suggestions": [{"id": "S1-1", "round": 1, "suggestion": "加一段資安查核", "status": "declined",
                                      "planner_reason": "讀者搜尋的是出金，資安段會稀釋主題"}]}
            (run / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            items = collect([run])
            items[0]["id"] = "D1"
            text = render(items, POLICY)
        self.assertIn("加一段資安查核", text)
        self.assertIn("讀者搜尋的是出金", text)
        self.assertIn("LEGAL", text)
        for leak in ("v81", "v8", "runtime", "Planner", "Auditor"):
            self.assertNotIn(leak, text)


class DecisionV81EmptyTests(unittest.TestCase):
    def test_missing_inputs_never_adopt(self):
        from eval_v81 import decide
        prereg = {"registered": {"v6_baseline": ["a"], "v8_conflict": ["b"], "v8_normal": "c", "v8_control": "f",
                                 "v81_conflict": ["d"], "v81_normal": "e"},
                  "file_sha256": {"roles_v81.py": "r", "workflow_v8.py": "w", "roles_v8.py": "x"}, "policy_v8_sha256": "p",
                  "system_prompt_sha256": {}, "fixed": {"cli_version": "", "model": ""}}
        result = decide(prereg, {}, [], [{}, {}], [])
        self.assertFalse(result["adopt_v81"])
        self.assertTrue(result["incomplete"])
        self.assertFalse(any(result["conditions"].values()))


if __name__ == "__main__":
    unittest.main()
