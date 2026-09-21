# Is rwkv-small's collapse about the model, or about K=30 being wide?
#
# The first version of this probe reseeded the option subset per case, so at
# K=4 a collapsed model could only answer CWE-787 on the ~13% of cases whose
# menu happened to contain it. That draws a collapse curve out of availability
# alone -- the instrument could not have failed to agree. So: ONE menu per K,
# shared by all 40 cases, always containing CWE-787, in a fixed order. Now
# 787's share is comparable across K.
#
#   ~89% at K=4  -> flat collapse, width is not the story
#   ~25% -> 89%  -> genuine width effect, and we can say where it breaks
#
# Qwen3.8-27B (0.744 on the board, same harness) is the control: if it holds
# flat while RWKV-small degrades, K=30 is a property of the task, not a bug.
# No gold is read; the measure is the answer distribution.
import json, random, re, sys, time, urllib.request
from collections import Counter
from pathlib import Path

REPO = Path("/Users/zhengruqi/Documents/Projects/trapstreet-solutions/cve_weakness_class/"
            "lexical/.trap/repos/decision-layer-bench-f48b32e8/tasks/cve_weakness_class")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0 Safari/537.36")
EP = "https://simple-jev-demo-api.featherless.ai/v1/classifier"
OPTION = re.compile(r"^(CWE-\d+):\s*(.+)$", re.MULTILINE)
COLLAPSE = "CWE-787"          # the label rwkv-small pinned on 89% of the 1500

options = dict(OPTION.findall((REPO / "inputs" / "task.md").read_text()))
picked = random.Random(7).sample(sorted((REPO / "inputs").glob("case_*")), 40)
states = [(c / "description.txt").read_text().strip() for c in picked]

rest = [k for k in options if k != COLLAPSE]
random.Random(99).shuffle(rest)

for model in ["featherless-ai/RWKV-small-classifier", "featherless-ai/Qwen3.8-27B-classifier"]:
    print(f"\n## {model}", flush=True)
    for K in (4, 8, 16, 30):
        menu = [COLLAPSE] + rest[: K - 1]
        random.Random(7).shuffle(menu)
        sub = {k: options[k] for k in menu}
        answers, confs = [], []
        for state in states:
            body = json.dumps({
                "model": model, "state": state,
                "questions": {"cwe": {"type": "choice",
                                      "instructions": "Which CWE weakness class best matches this vulnerability?",
                                      "criteria": sub}},
            }).encode()
            req = urllib.request.Request(
                EP, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
            try:
                a = json.loads(urllib.request.urlopen(req, timeout=120).read())["answers"]["cwe"]
                answers.append(a["choice"])
                if a.get("confidence") is not None:
                    confs.append(float(a["confidence"]))
            except Exception as e:
                answers.append(f"ERR:{type(e).__name__}")
            time.sleep(0.55)
        c = Counter(answers)
        top, ntop = c.most_common(1)[0]
        mc = sum(confs) / len(confs) if confs else float("nan")
        print(f"K={K:2d}  {COLLAPSE}={c[COLLAPSE]}/40 ({c[COLLAPSE]/40:.0%})  "
              f"distinct={len(c):2d}/{K}  top={top} {ntop}/40  mean_conf={mc:.3f}", flush=True)
