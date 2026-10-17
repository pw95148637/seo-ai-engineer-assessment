"""v7 prompts and the balance analysis; offline, no model calls."""
import json, tempfile, unittest
from pathlib import Path
import roles, roles_v7
from analyze_balance import analyze
from case_input import load_case
from workflow import snapshot, validate

HERE = Path(__file__).resolve().parent
POLICY = json.loads((HERE / "policy.json").read_text(encoding="utf-8"))


def ctx(iteration, scenario="forced_conflict"):
    _, s = load_case(scenario, "offline_fixture", POLICY["version"])
    s.iteration = iteration
    return snapshot(s)


class PromptV7Tests(unittest.TestCase):
    def test_planner_still_has_no_rulebook(self):
        user = json.loads(roles_v7.build_messages("planner", ctx(2), POLICY)[1]["content"])
        self.assertNotIn("policy", user)
        self.assertIn("policy", json.loads(roles_v7.build_messages("auditor", ctx(2), POLICY)[1]["content"]))

    def test_first_round_keeps_the_verbatim_demand_but_no_fallback(self):
        system = roles_v7.build_messages("planner", ctx(1), POLICY)[0]["content"]
        self.assertIn("必須逐字包含", system)
        self.assertIn("不要預先提出退讓方案或替代標題", system)

    def test_auditor_gives_direction_not_copy(self):
        system = roles_v7.build_messages("auditor", ctx(1), POLICY)[0]["content"]
        self.assertIn("不要代寫可直接採用的完整標題、小標或段落", system)
        self.assertIn("intent", roles_v7.output_schema("auditor")["properties"]["findings"]["items"]["required"])

    def test_no_example_answers_from_the_task_in_prompts(self):
        # The task's example compromise must not be planted in the prompts; it lives only in policy.json, unchanged.
        for role in ("planner", "auditor"):
            for it in (1, 2):
                system = roles_v7.build_messages(role, ctx(it), POLICY)[0]["content"]
                for word in ("資安", "勝率"):
                    self.assertNotIn(word, system)

    def test_v7_outputs_pass_the_unchanged_workflow_validation(self):
        validate("planner", {"title": "t", "sections": ["s"], "negotiation_note": "",
                             "responses": [{"quote": "q", "action": "counter", "wording": "w", "click_value": "c"}]})
        validate("auditor", {"passed": False, "note": "", "findings": [
            {"quote": "q", "reason": "r", "revision": "v", "intent": "i", "rule": "CLAIMS"}]})

    def test_v6_prompts_are_untouched(self):
        self.assertNotIn("responses", json.dumps(roles.output_schema("planner")))
        self.assertIn("有閱讀吸引力的可執行替代方向", roles.build_messages("auditor", ctx(1), POLICY)[0]["content"])


def fake_run(tmp, planners, auditors, final, status="approved_provisional"):
    history = []
    for i in sorted(planners):
        history.append({"node": "planner", "iteration": i, "output": planners[i]})
        if i in auditors:
            history.append({"node": "auditor", "iteration": i, "output": auditors[i]})
    state = {"scenario": "forced_conflict", "status": status, "iteration": max(planners), "history": history,
             "final": final}
    root = Path(tmp)
    (root / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    (root / "metadata.json").write_text(json.dumps({"prompt_version": "v7"}), encoding="utf-8")
    return root


class BalanceAnalysisTests(unittest.TestCase):
    def test_adopted_own_and_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = {"title": "娛樂城推薦：保證出金的祕密", "sections": ["前言一段原文內容", "第二段原文內容"], "negotiation_note": ""}
            a1 = {"passed": False, "note": "", "findings": [
                {"quote": "娛樂城推薦：保證出金的祕密", "reason": "r", "revision": "改成：出金卡關前必查的五個條款清單", "rule": "CLAIMS"},
                {"quote": "前言一段原文內容", "reason": "r", "revision": "請改寫為說明查核方法的前言段落", "rule": "CLAIMS"},
                {"quote": "第二段原文內容", "reason": "r", "revision": "刪除並換成風險提醒的完整段落", "rule": "LEGAL"}]}
            p2 = {"title": "出金卡關前必查的五個條款清單", "sections": ["我自己重寫的前言", "第二段原文內容"], "negotiation_note": ""}
            a2 = {"passed": True, "note": "", "findings": []}
            r = analyze(fake_run(tmp, {1: p1, 2: p2}, {1: a1, 2: a2}, p2))
            self.assertEqual([f["outcome"] for f in r["findings"]], ["adopted", "own", "kept"])
            self.assertEqual(r["m2"]["defence_accepted"], 1)
            self.assertEqual(r["m1"]["auditor_share_title"], 1.0)

    def test_text_from_planner_note_is_not_credited_to_auditor(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = {"title": "標題保證出金", "sections": ["段落"], "negotiation_note": "備案：出金卡關前必查的五個條款"}
            a1 = {"passed": False, "note": "", "findings": [
                {"quote": "標題保證出金", "reason": "r", "revision": "用 Planner 的備案：出金卡關前必查的五個條款", "rule": "CLAIMS"}]}
            p2 = {"title": "出金卡關前必查的五個條款", "sections": ["段落"], "negotiation_note": ""}
            r = analyze(fake_run(tmp, {1: p1, 2: p2}, {1: a1, 2: {"passed": True, "note": "", "findings": []}}, p2))
            self.assertEqual(r["m1"]["auditor_share_title"], 0.0)

    def test_v6_formal_run_baseline(self):
        r = analyze(HERE / "evidence" / "runtime-claude-conflict-v6")
        self.assertEqual((r["m2"]["adopted"], r["m2"]["own"], r["m2"]["kept"]), (7, 0, 0))
        self.assertAlmostEqual(r["m1"]["auditor_share"], 0.2578, places=4)


class RunnerV7Tests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_uses_v7_prompts_and_records_them(self):
        import contextlib, io, sys
        from run_claude import execute, parser
        from test_claude_adapter import FAKE
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake.py"
            fake.write_text(FAKE % "conflict", encoding="utf-8")
            out = Path(tmp) / "run"
            args = parser().parse_args(["--scenario", "forced_conflict", "--prompts", "v7", "--out", str(out)])
            with contextlib.redirect_stdout(io.StringIO()):
                status = await execute(args, cli=[sys.executable, str(fake)])
            self.assertEqual(status, 0)
            meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual((meta["prompt_version"], meta["roles_module"]), ("v7", "roles_v7.py"))
            first = json.loads((out / "provider.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("responses", json.dumps(first["request"]["json_schema"]))
            self.assertIn("定稿的寫法由你負責", first["request"]["system_prompt"])


if __name__ == "__main__":
    unittest.main()
