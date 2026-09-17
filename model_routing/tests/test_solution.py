import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "calibration"))
import calibrate  # noqa: E402
import solution  # noqa: E402

Q = {"question": "Which?", "options": {"A": "one", "B": "two", "C": "three"}}


class FakeClaude:
    """Answers by model: {model: [reply, ...]} consumed in order."""

    def __init__(self, replies):
        self.replies = {m: list(r) for m, r in replies.items()}
        self.calls = []
        self.messages = self

    def create(self, model, max_tokens, messages):
        self.calls.append((model, messages[0]["content"]))
        text = self.replies[model].pop(0)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


class FakeJev:
    def __init__(self, p):
        self.p, self.states, self.input_tokens = p, [], 500

    def noul(self, state, instructions):
        self.states.append((state, instructions))
        return self.p

    def cost_line(self):
        return solution.Jev.cost_line(self)


def run(arm, replies, jev_p=None):
    client = FakeClaude(replies)
    jev = FakeJev(jev_p)
    choice, up, lines = solution.route(arm, Q, client, jev_factory=lambda: jev)
    return choice, up, lines, client, jev


def test_single_model_arms_call_one_model_once():
    for arm, model in (("haiku-only", "claude-haiku-4-5"), ("opus-only", "claude-opus-5")):
        choice, up, _, client, _ = run(arm, {model: ["ANSWER: B"]})
        assert (choice, up) == ("B", False) and [m for m, _ in client.calls] == [model]


@pytest.mark.parametrize("p,expected_up", [(0.9, True), (solution.THRESHOLDS["jev-cascade-30"], True), (0.2, False)])
def test_jev_cascade_escalates_at_or_above_threshold(p, expected_up):
    choice, up, lines, client, jev = run("jev-cascade-30", {"claude-haiku-4-5": ["ANSWER: A"], "claude-opus-5": ["ANSWER: C"]}, p)
    assert up is expected_up and choice == ("C" if expected_up else "A")
    assert [m for m, _ in client.calls] == (["claude-haiku-4-5", "claude-opus-5"] if expected_up else ["claude-haiku-4-5"])
    assert jev.states[0][0]["proposed_answer"] == "A. one" and jev.states[0][1] == solution.CASCADE_Q
    assert any(l.startswith("UNMETERED_COST_USD:") for l in lines)


def test_cascade_escalates_without_asking_jev_when_haiku_gives_no_answer():
    choice, up, _, _, jev = run("jev-cascade-60", {"claude-haiku-4-5": ["no idea"], "claude-opus-5": ["ANSWER: B"]}, 0.0)
    assert (choice, up) == ("B", True) and jev.states == []


def test_preroute_skips_haiku_when_escalating_and_shows_jev_no_answer():
    choice, up, _, client, jev = run("jev-preroute-30", {"claude-opus-5": ["ANSWER: B"]}, 0.95)
    assert (choice, up) == ("B", True) and [m for m, _ in client.calls] == ["claude-opus-5"]
    assert "proposed_answer" not in jev.states[0][0] and jev.states[0][1] == solution.PRE_ROUTE_Q


def test_random_is_fixed_by_question_text_and_blind_to_answers():
    u = solution.draw(Q)
    assert 0 <= u < 1 and u == solution.draw(dict(Q))
    _, up, _, _, _ = run("random-30", {"claude-haiku-4-5": ["ANSWER: A"], "claude-opus-5": ["ANSWER: C"]})
    assert up is (u < 0.3)


def test_random_draw_escalates_about_the_target_share():
    shares = [solution.draw({"question": f"q{i}"}) < 0.3 for i in range(5000)]
    assert 0.28 < sum(shares) / len(shares) < 0.32


def test_haiku_verify_parses_p_wrong_and_unreadable_escalates(monkeypatch):
    monkeypatch.setitem(solution.THRESHOLDS, "haiku-verify-30", 0.5)
    replies = {"claude-haiku-4-5": ["ANSWER: A", "thinking\nP_WRONG: 20"], "claude-opus-5": ["ANSWER: C"]}
    choice, up, _, client, _ = run("haiku-verify-30", replies)
    assert (choice, up) == ("A", False) and "Proposed answer: A. one" in client.calls[1][1]
    replies = {"claude-haiku-4-5": ["ANSWER: A", "unsure"], "claude-opus-5": ["ANSWER: C"]}
    assert run("haiku-verify-30", replies)[:2] == ("C", True)


def test_answer_outside_the_options_is_no_answer():
    assert run("haiku-only", {"claude-haiku-4-5": ["ANSWER: J"]})[0] is None


def test_prompts_are_identical_to_the_calibration_probe():
    probe = Path("/Users/zhengruqi/Documents/Projects/trapstreet-tasks-private/tasks/model_routing_probe/probe.py")
    if not probe.exists():
        pytest.skip("probe source is in the private task repo")
    import importlib.util
    spec = importlib.util.spec_from_file_location("probe", probe)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (solution.PROMPT, solution.PRE_ROUTE_Q, solution.CASCADE_Q) == (mod.PROMPT, mod.PRE_ROUTE_Q, mod.CASCADE_Q)
    assert solution.JEV_MODEL == mod.JEV_MODEL and solution.MAX_TOKENS == 16000


def test_thresholds_reproduce_from_scores():
    data = calibrate.rows()
    for arm, (key, share) in calibrate.TARGETS.items():
        if arm in solution.THRESHOLDS and all(r.get(key) is not None for r in data):
            t, _ = calibrate.threshold_for([r[key] for r in data], share)
            assert t == solution.THRESHOLDS[arm]


def test_calibration_scores_carry_no_answer_key():
    for r in calibrate.rows():
        assert not {"answer", "correct"} & set(r)


def test_every_arm_folder_names_its_arm_and_the_task():
    for arm in solution.ARMS:
        y = (ROOT / arm / "trap.yaml").read_text()
        assert f"--arm {arm}\n" in y and "model-routing:" in y and f"TRAP_AGENT={arm}" in (ROOT / arm / ".envrc").read_text()


def test_first_answer_is_printed_only_when_haiku_answered_before_routing():
    _, _, lines, _, _ = run("random-60", {"claude-haiku-4-5": ["ANSWER: A"], "claude-opus-5": ["ANSWER: C"]})
    assert "FIRST_ANSWER: A" in lines
    _, _, lines, _, _ = run("jev-cascade-30", {"claude-haiku-4-5": ["none"], "claude-opus-5": ["ANSWER: C"]}, 0.1)
    assert not any(l.startswith("FIRST_ANSWER") for l in lines)
    _, _, lines, _, _ = run("jev-preroute-30", {"claude-haiku-4-5": ["ANSWER: A"]}, 0.1)
    assert not any(l.startswith("FIRST_ANSWER") for l in lines)


def test_every_arm_pins_the_current_task_commit():
    for arm in solution.ARMS:
        assert "trapstreet-tasks@7f36c68b831fbc1454961ceab9bec4f2313bff22#" in (ROOT / arm / "trap.yaml").read_text()


@pytest.mark.parametrize("reply,expected", [
    ("**ANSWER: B**", "B"), ("> **ANSWER:** B", "B"), ("- ANSWER: (B)", "B"),
    ("ANSWER: B", "B"), ("ANSWER: Bat", None), ("ANSWER: J", None)])
def test_markdown_around_the_answer_is_read(reply, expected):
    assert run("haiku-only", {"claude-haiku-4-5": [reply]})[0] == expected


def test_solution_and_judge_parse_answers_the_same_way():
    judge_path = Path("/Users/zhengruqi/Documents/Projects/trapstreet-tasks-private/tasks/model_routing/judge.py")
    if not judge_path.exists():
        pytest.skip("judge is in the private task repo")
    import importlib.util
    spec = importlib.util.spec_from_file_location("mr_judge", judge_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for text in ("**ANSWER: G**", "ANSWER: A", "- ANSWER: (B)", "ANSWER: Cat", "x\n**ANSWER: C**\n**ANSWER: D**"):
        assert solution.ANSWER_RE.findall(text) == mod.ANSWER_RE.findall(text), text


def test_jev_retries_then_gives_up(monkeypatch):
    calls = []

    class Flaky(FakeJev):
        def __init__(self, fails):
            super().__init__(0.9)
            self.fails = fails

        def noul(self, state, instructions):
            calls.append(1)
            if len(calls) <= self.fails:
                raise RuntimeError("529 high traffic")
            return super().noul(state, instructions)

    monkeypatch.setattr(solution.time, "sleep", lambda s: None)
    real = solution.Jev.noul
    flaky = Flaky(3)
    # drive the real retry loop with a client that fails three times
    class Client:
        def __init__(self, fails): self.n, self.fails = 0, fails
        def system_one(self, **kw):
            self.n += 1
            if self.n <= self.fails:
                raise RuntimeError("529 high traffic")
            return SimpleNamespace(nouls={"q": SimpleNamespace(noul=0.7)}, usage=SimpleNamespace(input_tokens=10))
    jev = solution.Jev.__new__(solution.Jev)
    jev.client, jev.input_tokens = Client(3), 0
    assert real(jev, {}, "q?") == 0.7 and jev.input_tokens == 10
    jev2 = solution.Jev.__new__(solution.Jev)
    jev2.client, jev2.input_tokens = Client(solution.JEV_RETRIES + 1), 0
    with pytest.raises(RuntimeError, match="Jev unreachable"):
        real(jev2, {}, "q?")
