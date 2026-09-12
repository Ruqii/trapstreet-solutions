"""The jail every dabstep harness runs its model-driven process in.

Why: this machine holds the answers (the private task repo, the DABStep
download in ~/.cache, the grader's packs, other runs' transcripts). Blocking the
network was not enough: agents that could not find an answer went looking for
it on disk. So the model-driven process -- Claude Code, DSH, or mini-loop's
snippet interpreter -- runs under macOS Seatbelt with a deny-by-default
profile: nothing is readable unless listed here, so $HOME, /tmp and every other
case's scratch directory are unreadable because they are never allowed, not
because they are denied by name. The profile's shape is apps/grader's
(trapstreet/trapstreet, src/grader/isolation.py), which runs a task's judge
the same way.

What a jailed process gets:
  read    the system trees (SYSTEM_READ_PATHS: /usr, /bin, /opt for Homebrew's
          python3/pandas/node, /System, ...), the per-case root, and whatever
          the harness adds with `readable` (its own install, read-only)
  write   the per-case root only (the case copy, a fresh $HOME and $TMPDIR)
  network one TCP port on loopback: the tp cost proxy. Nothing else, not even
          other loopback services.
  exec    anything readable, except the few binaries that hand work to a
          process outside the jail (open, osascript, security, pbpaste/pbcopy).

Usage from Python: `new_case_root()`, then `wrap(cmd, root=..., port=...)` and
`jail_env(env, root)`. From a shell (which also
applies jail_env, attests, and can stop the command after --timeout seconds):
    python3 sandbox.py --root DIR [--ro DIR]... [--port N] [--timeout S] -- cmd args...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

#: System trees any jailed process may read (apps/grader's list). Not /tmp,
#: /private/tmp or /private/var: other cases' scratch lives there.
SYSTEM_READ_PATHS = (
    "/usr", "/bin", "/sbin", "/private/etc", "/Library/Frameworks", "/opt", "/System",
    "/private/var/select", "/private/var/db", "/dev",
)
#: Single paths, stat-able and traversable but not listable. "/" and "/var" are
#: load-bearing (the loader; the timezone database) -- see apps/grader.
SYSTEM_READ_LITERALS = ("/", "/etc", "/var", "/dev/null")
#: Binaries that would run something outside the jail on the jail's behalf.
NO_EXEC = ("/usr/bin/open", "/usr/bin/osascript", "/usr/bin/security",
           "/usr/bin/pbpaste", "/usr/bin/pbcopy", "/usr/bin/sudo")


def _q(path: Path | str) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ancestors(path: Path) -> list[Path]:
    """Every directory above `path`, so it can be stat-ed on the way down
    (metadata only: an ancestor stays unlistable)."""
    return [p for p in path.parents if str(p) != "/"]


def proxy_port(url: str) -> int:
    """The loopback port of a tp cost-proxy URL; refuses anything else."""
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or not parsed.port:
        raise SystemExit(f"{url!r} is not the tp cost proxy (http://127.0.0.1:<port>)")
    return parsed.port


def profile(*, root: Path, readable: list[Path], port: int | None) -> str:
    root = Path(os.path.realpath(root))
    reads = [root, *(Path(os.path.realpath(p)) for p in readable)]
    read = " ".join([*(f"(subpath {_q(p)})" for p in reads),
                     *(f"(subpath {_q(p)})" for p in SYSTEM_READ_PATHS),
                     *(f"(literal {_q(p)})" for p in SYSTEM_READ_LITERALS)])
    meta = " ".join(sorted({f"(literal {_q(a)})" for p in reads for a in _ancestors(p)}))
    rules = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow signal (target same-sandbox))",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow ipc-posix-shm*)",
        "(allow pseudo-tty)",
        f"(allow file-read* {read})",
        f"(allow file-read-metadata {meta})" if meta else "",
        f"(allow file-write* (subpath {_q(root)}) (subpath \"/dev\"))",
        "(allow file-ioctl (subpath \"/dev\"))",
        "(deny process-exec " + " ".join(f"(literal {_q(p)})" for p in NO_EXEC) + ")",
        "(deny mach-lookup (global-name \"com.apple.pasteboard.1\"))",
        "(deny network*)",
    ]
    if port is not None:
        rules.append(f'(allow network-outbound (remote ip "localhost:{port}"))')
    return " ".join(r for r in rules if r)


def new_case_root(prefix: str = "dabstep-case-") -> Path:
    """A fresh per-case directory under $TMPDIR with work/, home/ and tmp/."""
    root = Path(os.path.realpath(tempfile.mkdtemp(prefix=prefix)))
    for sub in ("work", "home", "tmp"):
        (root / sub).mkdir()
    return root


def jail_env(env: dict[str, str], root: Path) -> dict[str, str]:
    """`env` with $HOME and every temp-dir variable pointed inside the case root."""
    out = dict(env)
    out.update(HOME=str(root / "home"), TMPDIR=str(root / "tmp") + "/", TMP=str(root / "tmp"),
               TEMP=str(root / "tmp"), XDG_CONFIG_HOME=str(root / "home/.config"),
               XDG_CACHE_HOME=str(root / "home/.cache"), XDG_DATA_HOME=str(root / "home/.local/share"),
               XDG_STATE_HOME=str(root / "home/.local/state"), MPLCONFIGDIR=str(root / "home/.matplotlib"))
    # SSH_AUTH_SOCK: the agent socket is outside the jail anyway. NODE_USE_SYSTEM_CA:
    # node reads the system trust store from the keychain at startup, which the
    # jail refuses, and node then crashes; a jailed process speaks plain HTTP to
    # the loopback cost proxy and needs no CA at all.
    for name in ("XDG_RUNTIME_DIR", "SSH_AUTH_SOCK", "NODE_USE_SYSTEM_CA"):
        out.pop(name, None)
    return out


def wrap(cmd: list[str], *, root: Path, readable: list[Path] = (), port: int | None = None) -> list[str]:
    """The argv that runs `cmd` in the jail. Refuses to run unjailed."""
    exe = shutil.which("sandbox-exec")
    if not exe:
        raise SystemExit("sandbox-exec is not on PATH; dabstep harnesses do not run unjailed")
    return [exe, "-p", profile(root=root, readable=list(readable), port=port), *cmd]


def attest(*, root: Path, readable: list[Path] = (), port: int | None = None) -> None:
    """Say on stderr, which tp keeps per case, that this case ran jailed and how.
    audit_transcripts.py refuses a case without this line."""
    text = profile(root=root, readable=list(readable), port=port)
    print(json.dumps({"event": "jail", "sandbox": "sandbox-exec", "root": str(root), "port": port,
                      "readable": [str(p) for p in readable],
                      "profile_sha256": hashlib.sha256(text.encode()).hexdigest()}),
          file=sys.stderr, flush=True)


def supervise(argv: list[str], env: dict[str, str], timeout: float | None) -> int:
    """Run `argv` and return its exit status, stopping it at `timeout` seconds
    (TERM, then KILL) and passing on a TERM this process receives. tp enforces
    its own timeout with SIGKILL, which no cleanup survives, so a harness has to
    stop itself first to keep its transcript."""
    child = subprocess.Popen(argv, env=env)
    signal.signal(signal.SIGTERM, lambda *_: child.terminate())
    try:
        return child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(json.dumps({"event": "timeout", "after_s": timeout}), file=sys.stderr, flush=True)
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        return 124


def main() -> int:
    parser = argparse.ArgumentParser(description="run a command in the dabstep jail")
    parser.add_argument("--root", required=True, type=Path, help="the per-case root (read-write)")
    parser.add_argument("--ro", action="append", default=[], type=Path, help="an extra read-only tree")
    parser.add_argument("--port", type=int, help="the one loopback port the command may connect to")
    parser.add_argument("--timeout", type=float, help="stop the command after this many seconds")
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        parser.error("no command")
    root = Path(os.path.realpath(args.root))
    argv = wrap(cmd, root=root, readable=args.ro, port=args.port)
    attest(root=root, readable=args.ro, port=args.port)
    return supervise(argv, jail_env(dict(os.environ), root), args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
