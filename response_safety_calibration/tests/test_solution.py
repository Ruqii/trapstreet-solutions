import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import solution  # noqa: E402

REAL_USAGE_LINE = solution.Jev.usage_line  # tests replace solution.Jev with a factory

CONVERSATION = {"context": [{"speaker": "USER", "text": "hi"}], "response": "hello there"}


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(name, args, id_="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=args, id=id_)


def message(blocks, stop):
    return SimpleNamespace(content=blocks, stop_reason=stop)


class FakeClaude:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.messages = self

    def create(self, **kw):
        self.requests.append(json.loads(json.dumps(kw, default=lambda o: o.__dict__)))
        return self.script.pop(0)


class FakeJev:
    def __init__(self):
        self.calls, self.seen = 0, []

    def ask(self, state, questions):
        self.calls += 1
        self.seen.append((state, dict(questions)))
        return {k: 0.3 for k in questions}

    def usage_line(self):
        return REAL_USAGE_LINE(self)

    input_tokens = 1000
    models = {"jev-1.13.0"}


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    (tmp_path / "task.md").write_text("TASK")
    (tmp_path / "conversation.json").write_text(json.dumps(CONVERSATION))
    monkeypatch.setenv("TRAP_MANIFEST", json.dumps({"inputs_dir": str(tmp_path), "outputs_dir": str(tmp_path)}))


def run(monkeypatch, capsys, arm, claude_script=(), jev=None):
    fake = FakeClaude(claude_script)
    jev = jev or FakeJev()
    monkeypatch.setattr(solution, "claude", lambda: fake)
    monkeypatch.setattr(solution, "Jev", lambda: jev)
    monkeypatch.setattr(sys, "argv", ["solution.py", "--arm", arm])
    solution.main()
    return capsys.readouterr().out, fake, jev


def last_answer(out):
    lines = [l for l in out.splitlines() if l.startswith("ANSWER:")]
    return float(lines[-1].split(":")[1]) if lines else None


def test_claude_alone_relays_answer(inputs, monkeypatch, capsys):
    out, fake, _ = run(monkeypatch, capsys, "claude-alone", [message([text("ok\nANSWER: 0.42")], "end_turn")])
    assert last_answer(out) == 0.42
    assert "temperature" not in fake.requests[0]  # rejected by Sonnet 5


def test_refusal_prints_no_answer(inputs, monkeypatch, capsys):
    out, _, _ = run(monkeypatch, capsys, "claude-alone", [message([], "refusal")])
    assert last_answer(out) is None and "REFUSED" in out


def test_sampled_uses_yes_share(inputs, monkeypatch, capsys):
    script = [message([text("YES")], "end_turn")] * 3 + [message([text("NO")], "end_turn")] * 7
    out, fake, _ = run(monkeypatch, capsys, "claude-alone-sampled", script)
    assert len(fake.requests) == solution.SAMPLES and last_answer(out) == pytest.approx(0.3)


def test_sampled_ignores_unparseable_votes(inputs, monkeypatch, capsys):
    script = [message([text("YES")], "end_turn")] * 5 + [message([text("maybe")], "end_turn")] * 5
    out, _, _ = run(monkeypatch, capsys, "claude-alone-sampled", script)
    assert last_answer(out) == 1.0
    assert "votes: yes=5 no=0 refused=0 unparseable=5" in out


def test_sampled_overrides_task_answer_format(inputs, monkeypatch, capsys):
    # First run: without an explicit override Claude followed task.md and wrote
    # "ANSWER: 0.05" instead of voting.
    _, fake, _ = run(monkeypatch, capsys, "claude-alone-sampled", [message([text("NO")], "end_turn")] * 10)
    req = fake.requests[0]
    assert "ANSWER" in req["system"] and "YES or NO" in req["system"]
    assert "Do not write an ANSWER line" in req["messages"][0]["content"]


def test_sampled_probability_reply_is_not_called_a_refusal(inputs, monkeypatch, capsys):
    out, _, _ = run(monkeypatch, capsys, "claude-alone-sampled", [message([text("ANSWER: 0.05")], "end_turn")] * 10)
    assert last_answer(out) is None and "REFUSED" not in out and "no usable votes" in out
    assert "unparseable=10" in out


def test_sampled_all_refusals_print_refused(inputs, monkeypatch, capsys):
    out, _, _ = run(monkeypatch, capsys, "claude-alone-sampled", [message([], "refusal")] * 10)
    assert "REFUSED" in out and "refused=10" in out


def test_jev_alone_asks_one_overall_noul(inputs, monkeypatch, capsys):
    out, fake, jev = run(monkeypatch, capsys, "jev-alone")
    assert jev.calls == 1 and fake.requests == [] and last_answer(out) == 0.3
    assert jev.seen[0][0] == CONVERSATION


def test_single_arm_caps_jev_at_one_call(inputs, monkeypatch, capsys):
    script = [
        message([tool_use("ask_jev", {}, "a"), tool_use("ask_jev", {}, "b")], "tool_use"),
        message([text("ANSWER: 0.35")], "end_turn"),
    ]
    out, fake, jev = run(monkeypatch, capsys, "claude-jev-single", script)
    assert jev.calls == 1 and last_answer(out) == 0.35
    results = fake.requests[1]["messages"][-1]["content"]
    assert [r.get("is_error", False) for r in results] == [False, True]


def test_decomposed_arm_asks_five_reasons_in_one_call(inputs, monkeypatch, capsys):
    script = [message([tool_use("ask_jev_reasons", {})], "tool_use"), message([text("ANSWER: 0.6")], "end_turn")]
    out, _, jev = run(monkeypatch, capsys, "claude-jev-decomposed", script)
    assert jev.calls == 1 and set(jev.seen[0][1]) == set(solution.REASONS)


def test_freeform_respects_what_jev_may_see(inputs, monkeypatch, capsys):
    script = [
        message([tool_use("ask_jev", {"question": "Is it rude?", "sees": "final_response_only"})], "tool_use"),
        message([tool_use("ask_jev", {"question": "Unsafe overall?", "sees": "whole_conversation"}, "t2")], "tool_use"),
        message([text("ANSWER: 0.2")], "end_turn"),
    ]
    out, _, jev = run(monkeypatch, capsys, "claude-jev-freeform", script)
    assert jev.seen[0][0] == {"response": "hello there"} and jev.seen[1][0] == CONVERSATION
    assert "JEV_USAGE: calls=2" in out and last_answer(out) == 0.2


def test_jev_failure_is_reported_to_claude_not_fatal(inputs, monkeypatch, capsys):
    class Boom(FakeJev):
        def ask(self, state, questions):
            raise RuntimeError("down")
    script = [message([tool_use("ask_jev", {})], "tool_use"), message([text("ANSWER: 0.5")], "end_turn")]
    out, fake, _ = run(monkeypatch, capsys, "claude-jev-single", script, jev=Boom())
    assert fake.requests[1]["messages"][-1]["content"][0]["is_error"] is True and last_answer(out) == 0.5


def test_jev_arms_report_unmetered_cost(inputs, monkeypatch, capsys):
    out, _, _ = run(monkeypatch, capsys, "jev-alone")
    line = [l for l in out.splitlines() if l.startswith("UNMETERED_COST_USD:")]
    assert line and float(line[0].split(":")[1]) == pytest.approx(1000 * 0.042 / 1e6)


def test_claude_only_arm_reports_no_unmetered_cost(inputs, monkeypatch, capsys):
    out, _, _ = run(monkeypatch, capsys, "claude-alone", [message([text("ANSWER: 0.4")], "end_turn")])
    assert "UNMETERED_COST_USD" not in out
