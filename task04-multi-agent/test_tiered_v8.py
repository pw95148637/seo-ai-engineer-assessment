"""v8 tiers (MUST/SHOULD), program checks, prompts and measurements; offline, no model calls."""
import contextlib, copy, io, json, shutil, sys, tempfile, textwrap, unittest
from pathlib import Path
import roles, roles_v8
from case_input import load_case
from workflow import snapshot
from workflow_v8 import TieredState, derive_review, program_findings, run, validate

HERE = Path(__file__).resolve().parent
POLICY = json.loads((HERE / "policy_v8.json").read_text(encoding="utf-8"))
V5 = json.loads((HERE / "policy.json").read_text(encoding="utf-8"))


def sec(heading, points="要點"):
    return {"heading": heading, "points": points}


def finding(quote, rule="CLAIMS"):
    return {"quote": quote, "reason": "讀者會誤以為有保證", "revision": "改寫成查核問題", "rule": rule}


BAD = {"title": "娛樂城推薦：保證出金是真的嗎？", "sections": [sec("前言"), sec("出金條款")], "negotiation_note": "",
       "suggestion_responses": []}
GOOD = {"title": "娛樂城推薦前必看：出金條款5問", "sections": [sec("前言"), sec("出金條款")], "negotiation_note": "",
        "suggestion_responses": []}


class Script:
    """Replays fixed Planner and Auditor outputs per round; records the contexts it was given."""
    def __init__(self, planner, auditor):
        self.planner, self.auditor, self.calls, self.seen = planner, auditor, 0, []

    async def __call__(self, role, state):
        self.calls += 1
        self.seen.append((role, copy.deepcopy(state)))
        return copy.deepcopy((self.planner if role == "planner" else self.auditor)[state["iteration"] - 1])


def tiered(**kw):
    return TieredState(mode="offline_fixture", **kw)


class ProgramCheckTests(unittest.TestCase):
    def test_literal_terms_blocked_in_title_heading_and_points(self):
        draft = {"title": "穩賺不賠？", "sections": [sec("保證出金的真相", "拆解「保證出金」廣告")]}
        hits = program_findings(draft, POLICY)
        self.assertEqual([(h["quote"], h["rule"], h["source"]) for h in hits],
                         [("穩賺不賠？", "CLAIMS", "program"), ("保證出金的真相", "CLAIMS", "program"),
                          ("拆解「保證出金」廣告", "CLAIMS", "program")])

    def test_listed_guarantee_words_blocked_in_title_and_headings_only(self):
        for word in ("零風險", "包贏", "只賺不賠", "秒出金"):
            self.assertTrue(program_findings({"title": f"娛樂城{word}嗎", "sections": [sec("前言")]}, POLICY), word)
            self.assertTrue(program_findings({"title": "娛樂城推薦", "sections": [sec(f"{word}的宣傳")]}, POLICY), word)
            # CLAIMS lets content points describe an advertising claim; only judgment can tell, so code stays out.
            self.assertEqual(program_findings({"title": "娛樂城推薦",
                                               "sections": [sec("話術拆解", f"廣告說法：{word}")]}, POLICY), [], word)

    def test_judgment_rules_are_not_keyword_lists(self):
        # Encouraging bets or implying legality is left to the Auditor (a keyword list would miss or over-block).
        draft = {"title": "娛樂城推薦", "sections": [sec("避坑清單", "不借錢、不用生活費下注"),
                                                     sec("合法休閒選擇", "公益彩券、運動彩券的官方管道")]}
        self.assertEqual(program_findings(draft, POLICY), [])

    def test_format_and_fields(self):
        validate("planner", GOOD, POLICY)
        for bad in ({**GOOD, "sections": ["字串段落"]}, {**GOOD, "sections": [sec("")]},
                    {**GOOD, "suggestion_responses": [{"id": "S1-1", "action": "maybe", "reason": ""}]}):
            with self.assertRaises(ValueError):
                validate("planner", bad, POLICY)
        validate("auditor", {"findings": [finding("x")], "suggestions": ["加一段資安查核"], "note": ""}, POLICY)
        for bad in ({"findings": [finding("x", rule="UTILITY")], "suggestions": [], "note": ""},
                    {"findings": [{"quote": "x", "reason": "", "revision": "r", "rule": "CLAIMS"}], "suggestions": [], "note": ""},
                    {"findings": [], "suggestions": [""], "note": ""}):
            with self.assertRaises(ValueError):
                validate("auditor", bad, POLICY)


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_should_only_ends_the_loop_without_another_round(self):
        agent = Script([GOOD], [{"findings": [], "suggestions": ["加一段資安查核", "標題可加年份"], "note": "通過"}])
        s = await run(agent, tiered(), POLICY)
        self.assertEqual((s.status, s.iteration, agent.calls), ("approved_provisional", 1, 2))
        self.assertEqual([x["status"] for x in s.final["attached_suggestions"]], ["open", "open"])

    async def test_must_and_should_carried_separately_and_decline_reason_attached(self):
        planner = [BAD, {**GOOD, "suggestion_responses": [{"id": "S1-1", "action": "decline", "reason": "會稀釋出金主題"}]}]
        auditor = [{"findings": [finding("前言", "LEGAL")], "suggestions": ["加一段資安查核"], "note": ""},
                   {"findings": [], "suggestions": ["FAQ 可再具體"], "note": ""}]
        agent = Script(planner, auditor)
        s = await run(agent, tiered(), POLICY)
        self.assertEqual((s.status, s.iteration), ("approved_provisional", 2))
        review_seen = agent.seen[2][1]["review"]            # second Planner call
        self.assertEqual([m["source"] for m in review_seen["must"]], ["program", "auditor"])
        self.assertEqual([x["id"] for x in review_seen["should"]], ["S1-1"])
        self.assertNotIn("policy", json.loads(roles_v8.build_messages("planner", agent.seen[2][1], POLICY)[1]["content"]))
        attached = {x["id"]: x for x in s.final["attached_suggestions"]}
        self.assertEqual((attached["S1-1"]["status"], attached["S1-1"]["planner_reason"]), ("declined", "會稀釋出金主題"))
        self.assertEqual(attached["S2-1"]["status"], "open")

    async def test_program_check_blocks_even_when_auditor_finds_nothing(self):
        planner = [{**GOOD, "sections": [sec("零風險的出金方法")]}, GOOD]
        auditor = [{"findings": [], "suggestions": [], "note": ""}] * 2
        s = await run(Script(planner, auditor), tiered(), POLICY)
        self.assertEqual(s.iteration, 2)
        first = next(e for e in s.history if e["node"] == "decision")
        self.assertEqual((first["action"], first["review"]["must"][0]["source"]), ("revise", "program"))

    async def test_level_comes_from_policy_not_from_the_model(self):
        # A level written by a model is ignored; a cited rule is MUST because the policy says so.
        planner = [GOOD, GOOD]
        auditor = [{"findings": [{**finding("前言", "LEGAL"), "level": "SHOULD"}], "suggestions": [], "note": ""},
                   {"findings": [], "suggestions": [], "note": ""}]
        s = await run(Script(planner, auditor), tiered(), POLICY)
        self.assertEqual(s.iteration, 2)

    async def test_omission_finding_without_quote_still_blocks(self):
        auditor = [{"findings": [{"quote": "", "reason": "缺少刑責風險說明", "revision": "加一段法律風險", "rule": "LEGAL"}],
                    "suggestions": [], "note": ""}, {"findings": [], "suggestions": [], "note": ""}]
        s = await run(Script([GOOD, GOOD], auditor), tiered(), POLICY)
        self.assertEqual((s.status, s.iteration), ("approved_provisional", 2))

    async def test_suggestions_beyond_the_cap_are_dropped(self):
        auditor = [{"findings": [], "suggestions": ["一", "二", "三"], "note": ""}]
        s = await run(Script([GOOD], auditor), tiered(), POLICY)
        self.assertEqual([x["id"] for x in s.review["should"]], ["S1-1", "S1-2"])

    async def test_unknown_rule_is_a_format_error(self):
        auditor = [{"findings": [finding("前言", "UTILITY")], "suggestions": [], "note": ""}]
        s = await run(Script([GOOD], auditor), tiered(), POLICY)
        self.assertEqual(s.status, "error")
        self.assertIsNone(s.final)

    async def test_must_left_at_the_limit_goes_to_human_review(self):
        auditor = [{"findings": [finding("前言", "LEGAL")], "suggestions": [], "note": ""}] * 3
        agent = Script([GOOD] * 3, auditor)
        s = await run(agent, tiered(), POLICY)
        self.assertEqual((s.status, s.iteration, agent.calls), ("human_review", 3, 6))
        self.assertIsNone(s.final)

    async def test_silence_on_a_suggestion_is_recorded_as_unanswered(self):
        planner = [BAD, GOOD]
        auditor = [{"findings": [], "suggestions": ["加一段資安查核"], "note": ""},
                   {"findings": [], "suggestions": [], "note": ""}]
        s = await run(Script(planner, auditor), tiered(), POLICY)
        self.assertEqual(s.suggestions[0]["status"], "unanswered")
        self.assertEqual(s.final["attached_suggestions"][0]["id"], "S1-1")

    async def test_immutable_still_unsatisfiable(self):
        auditor = [{"findings": [], "suggestions": [], "note": ""}]
        s = await run(Script([BAD], auditor), tiered(immutable_conflict=True), POLICY)
        self.assertEqual(s.status, "unsatisfiable")


def ctx(iteration, scenario="forced_conflict"):
    _, s = load_case(scenario, "offline_fixture", POLICY["version"])
    s = TieredState(**{k: v for k, v in s.__dict__.items()})
    s.iteration = iteration
    return snapshot(s)


class PromptTests(unittest.TestCase):
    def test_must_rules_are_v5_verbatim_and_utility_is_not_a_rule(self):
        v5 = {r["id"]: r["instruction"] for r in V5["rules"]}
        self.assertEqual({r["id"]: r["instruction"] for r in POLICY["rules"]},
                         {k: v5[k] for k in ("CLAIMS", "EVIDENCE", "LEGAL")})
        self.assertTrue(all(r["level"] == "MUST" for r in POLICY["rules"]))
        self.assertEqual(roles_v8.output_schema("auditor")["properties"]["findings"]["items"]["properties"]["rule"]["enum"],
                         ["CLAIMS", "EVIDENCE", "LEGAL"])
        self.assertNotIn("passed", roles_v8.output_schema("auditor")["properties"])

    def test_every_sentence_states_what_it_guards_against(self):
        for role in ("planner", "auditor"):
            for it in (1, 2):
                pairs = roles_v8.sentences(role, ctx(it))
                self.assertTrue(all(s and why for s, why in pairs))
                self.assertEqual(roles_v8.build_messages(role, ctx(it), POLICY)[0]["content"], "".join(s for s, _ in pairs))

    def test_planner_has_no_rulebook_and_prompts_plant_no_example_answer(self):
        self.assertNotIn("policy", json.loads(roles_v8.build_messages("planner", ctx(2), POLICY)[1]["content"]))
        seen = json.loads(roles_v8.build_messages("auditor", ctx(2), POLICY)[1]["content"])["policy"]
        self.assertEqual([r["id"] for r in seen["rules"]], ["CLAIMS", "EVIDENCE", "LEGAL"])
        self.assertNotIn("RFC2119", [x["id"] for x in seen["sources"]])
        self.assertNotIn("suggestions", seen)
        for role in ("planner", "auditor"):
            for it in (1, 2):
                system = roles_v8.build_messages(role, ctx(it), POLICY)[0]["content"]
                for word in ("資安", "勝率"):
                    self.assertNotIn(word, system)

    def test_v8_prompts_are_shorter_than_v6(self):
        _, v6 = load_case("forced_conflict", "offline_fixture", "x")
        v6.iteration = 2
        for role in ("planner", "auditor"):
            self.assertLess(len(roles_v8.build_messages(role, ctx(2), POLICY)[0]["content"]),
                            len(roles.build_messages(role, snapshot(v6), V5)[0]["content"]))


FAKE_V8 = textwrap.dedent('''
    import json, sys
    args = sys.argv[1:]
    if args == ["--version"]:
        print("0.0.0-fake (Claude Code)"); sys.exit(0)
    context = json.loads(sys.stdin.buffer.read().decode("utf-8"))["context"]
    def reply(value):
        out = {"type": "result", "subtype": "success", "is_error": False, "structured_output": value,
               "modelUsage": {"fake-model": {}}, "usage": {"output_tokens": 1}, "duration_ms": 1, "session_id": "fake"}
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8")); sys.exit(0)
    sec = lambda h: {"heading": h, "points": "要點"}
    if "findings" in json.loads(args[args.index("--json-schema") + 1])["properties"]:
        if context["iteration"] == 1:
            reply({"findings": [{"quote": "前言", "reason": "r", "revision": "v", "rule": "LEGAL"}],
                   "suggestions": ["加一段資安查核"], "note": "退回"})
        reply({"findings": [], "suggestions": ["FAQ 可再具體"], "note": "通過"})
    if context["iteration"] == 1:
        reply({"title": "娛樂城推薦：保證出金？", "sections": [sec("前言")], "negotiation_note": "", "suggestion_responses": []})
    reply({"title": "娛樂城推薦前必看：出金條款", "sections": [sec("出金條款")], "negotiation_note": "改寫",
           "suggestion_responses": [{"id": "S1-1", "action": "decline", "reason": "會稀釋主題"}]})
''')


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_v8_end_to_end_and_tamper_detection(self):
        from run_claude import execute, parser
        from verify_run import inspect
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake.py"
            fake.write_text(FAKE_V8, encoding="utf-8")
            out = Path(tmp) / "run"
            args = parser().parse_args(["--scenario", "forced_conflict", "--prompts", "v8", "--out", str(out)])
            with contextlib.redirect_stdout(io.StringIO()):
                status = await execute(args, cli=[sys.executable, str(fake)])
            self.assertEqual(status, 0)
            meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual((meta["roles_module"], meta["policy_file"], meta["controller_module"]),
                             ("roles_v8.py", "policy_v8.json", "workflow_v8.py"))
            checks = json.loads((out / "verification.json").read_text(encoding="utf-8"))["checks"]
            for name in ("decisions_recomputed_from_policy", "no_round_for_should_only", "should_never_blocks",
                         "final_attaches_unadopted_suggestions", "first_round_blocked", "claude_cli_context_isolated"):
                self.assertTrue(checks[name], name)
            outline = (out / "outline.md").read_text(encoding="utf-8")
            self.assertIn("S1-1 加一段資安查核（Planner 不採納：會稀釋主題）", outline)
            self.assertIn("S2-1 FAQ 可再具體（最後一輪提出", outline)
            state = json.loads((out / "state.json").read_text(encoding="utf-8"))
            decision = next(e for e in state["history"] if e["node"] == "decision")
            decision["review"]["must"] = []                  # pretend the controller let a MUST item through
            (out / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            tampered = inspect(out)["checks"]
            self.assertFalse(tampered["decisions_recomputed_from_policy"])
            self.assertFalse(tampered["no_round_for_should_only"])


class ProbeAndScoringTests(unittest.TestCase):
    def test_program_hit_on_a_line_does_not_count_as_the_auditor_reading_it(self):
        from probe_auditor import judge_v8
        case = {"expect": "must", "planted": ["零風險", "穩穩賺"]}
        draft = {"title": "娛樂城推薦｜零風險穩穩賺", "sections": [sec("前言")]}
        silent = {"findings": [], "suggestions": [], "note": ""}
        review = derive_review(1, program_findings(draft, POLICY), silent, POLICY)
        verdict = judge_v8(case, review, silent)
        self.assertTrue(verdict["system_blocked"])
        self.assertEqual((verdict["auditor_missed"], verdict["as_expected"]), (["穩穩賺"], False))
        flagged = {"findings": [finding("娛樂城推薦｜零風險穩穩賺")], "suggestions": [], "note": ""}
        review = derive_review(1, program_findings(draft, POLICY), flagged, POLICY)
        self.assertTrue(judge_v8(case, review, flagged)["as_expected"])

    def test_blind_package_renders_both_versions_alike(self):
        from eval_v8 import rendered_sections
        self.assertEqual(rendered_sections(["問題1：違法嗎？——刑法第266條", "前言：本文"]),
                         ["問題1：違法嗎？：刑法第266條", "前言：本文"])
        self.assertEqual(rendered_sections([sec("前言", "本文")]), ["前言：本文"])

    def test_missing_runs_or_no_v8_final_never_adopts(self):
        from eval_v8 import decide
        prereg = {"registered": {"v6_baseline": ["a"], "v6_drift": "d", "v8_conflict": ["b"], "v8_normal": "n",
                                 "company_rows_sha256": "x"},
                  "file_sha256": {"roles_v8.py": "r", "workflow_v8.py": "w", "cases/auditor_probe_v8.json": "c",
                                  "cases/company_samples_v8.json": "s"}, "policy_v8_sha256": "p"}
        empty = {"results": [], "errors": [], "claude_cli_context_isolated": True}
        result = decide(prereg, {}, [], [{}, {}], empty, empty)
        self.assertFalse(result["adopt_v8"])
        self.assertTrue(result["incomplete"])
        self.assertFalse(any(result["conditions"].values()))


class RaterTests(unittest.IsolatedAsyncioTestCase):
    async def test_rater_call_is_isolated_and_reads_the_package_from_stdin(self):
        from blind_rate import rate
        fake = textwrap.dedent('''
            import json, os, sys
            args = sys.argv[1:]
            if args == ["--version"]:
                print("0"); sys.exit(0)
            ok = "--safe-mode" in args and not os.listdir(".") and os.environ.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") == "1"
            text = sys.stdin.buffer.read().decode("utf-8")
            out = {"type": "result", "subtype": "success", "is_error": not ok, "usage": {"input_tokens": 5},
                   "structured_output": {"ratings": [{"label": "A", "click_appeal": 3, "click_reason": text[:4],
                                                      "reading_value": 3, "reading_reason": "", "violations": []}]}}
            sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
        ''')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fake.py"
            path.write_text(fake, encoding="utf-8")
            code, stdout, _, _ = await rate("# 文章大綱評分", [sys.executable, str(path)])
        envelope = json.loads(stdout)
        self.assertFalse(envelope["is_error"])
        self.assertEqual(envelope["structured_output"]["ratings"][0]["click_reason"], "# 文章")


class EarlierEvidenceTests(unittest.TestCase):
    def test_v6_v7_verification_reproduces_byte_for_byte(self):
        from verify_run import inspect
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("runtime-claude-conflict-v6", "runtime-claude-conflict-v6-repeat", "runtime-claude-conflict-v6-run3",
                         "runtime-claude-normal-v6", "runtime-claude-conflict-v7-1", "runtime-claude-conflict-v7-2",
                         "runtime-claude-conflict-v7-3", "runtime-claude-normal-v7"):
                src = HERE / "evidence" / name
                dst = Path(tmp) / name
                shutil.copytree(src, dst)
                inspect(dst)
                for f in ("verification.json", "summary.md"):
                    self.assertEqual((dst / f).read_bytes(), (src / f).read_bytes(), name + "/" + f)

    def test_v8_measurements_equal_v7_analysis_on_earlier_runs(self):
        from eval_v8 import analyze
        recorded = {r["run"]: r for r in json.loads(
            (HERE / "evidence/balance-v7/analysis.json").read_text(encoding="utf-8"))["runs"]}
        for name, old in recorded.items():
            new = analyze(HERE / "evidence" / name)
            self.assertEqual({k: new["m1"][k] for k in old["m1"]}, old["m1"], name)
            self.assertEqual({k: new["m2"][k] for k in ("adopted", "kept", "own", "defence_accepted")},
                             {k: old["m2"][k] for k in ("adopted", "kept", "own", "defence_accepted")}, name)


if __name__ == "__main__":
    unittest.main()
