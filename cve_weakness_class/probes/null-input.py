# Does the answer depend on the state at all?
#
# Same menu the graded runs used -- the 30 options in task.md's own order --
# with states that contain no vulnerability at all. If a model returns the
# label it already returns on 89% of real descriptions, then its output is a
# function of the menu, not of the input, and its score is not a measurement
# of anything about CVE text.
#
# rwkv-std is in here because it is already published at 0.229 and used only
# 17 of 30 labels; if it too ignores the state, that row has to come down.
import json, re, time, urllib.request
from pathlib import Path

REPO = Path("/Users/zhengruqi/Documents/Projects/trapstreet-solutions/cve_weakness_class/"
            "lexical/.trap/repos/decision-layer-bench-f48b32e8/tasks/cve_weakness_class")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0 Safari/537.36")
EP = "https://simple-jev-demo-api.featherless.ai/v1/classifier"
OPTION = re.compile(r"^(CWE-\d+):\s*(.+)$", re.MULTILINE)

options = dict(OPTION.findall((REPO / "inputs" / "task.md").read_text()))
assert len(options) == 30, len(options)

NULLS = {
    "period": ".",
    "pangram": "The quick brown fox jumps over the lazy dog.",
    "recipe": "Combine the flour, sugar and butter in a bowl and bake for forty minutes.",
    "weather": "Tomorrow will be cloudy with a chance of light rain in the afternoon.",
}
# what each model actually answered most often across the graded 1500
KNOWN = {
    "featherless-ai/RWKV-small-classifier": "CWE-787 (1336/1500, 11 labels used)",
    "featherless-ai/RWKV-std-classifier": "CWE-787 (525/1500, 17 labels used)",
    "featherless-ai/Qwen3.8-27B-classifier": "CWE-284 (153/1500, 30 labels used)",
}

for model in KNOWN:
    print(f"\n## {model}\n   graded run's modal answer: {KNOWN[model]}", flush=True)
    for name, state in NULLS.items():
        body = json.dumps({
            "model": model, "state": state,
            "questions": {"cwe": {"type": "choice",
                                  "instructions": "Which CWE weakness class best matches this vulnerability?",
                                  "criteria": options}},
        }).encode()
        req = urllib.request.Request(
            EP, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
        try:
            a = json.loads(urllib.request.urlopen(req, timeout=120).read())["answers"]["cwe"]
            print(f"   {name:9s} -> {a['choice']:9s} conf={a.get('confidence')}", flush=True)
        except Exception as e:
            print(f"   {name:9s} -> ERROR {type(e).__name__}: {str(e)[:120]}", flush=True)
        time.sleep(0.6)
