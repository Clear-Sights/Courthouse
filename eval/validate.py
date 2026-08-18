#!/usr/bin/env python3
"""Validate the Courthouse marketplace manifest.

Checks, stdlib + git only:
  1. marketplace.json parses and carries the required top-level fields.
  2. Every plugin entry has name, description, license, version, and a pinned
     source (ref + sha, sha 40 hex chars).
  3. Every pinned (repo, ref, sha) actually exists on the remote: the tag is
     reachable and its peeled commit equals the pinned sha.
  4. A git-subdir source's path exists in a shallow clone at the pinned ref.

Exit 0 iff every check passes.
"""
import json, pathlib, re, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / ".claude-plugin" / "marketplace.json"
failures = []

def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)

m = json.loads(MANIFEST.read_text())
check(m.get("name") == "courthouse", "marketplace name is 'courthouse'")
check(isinstance(m.get("owner"), dict) and m["owner"].get("url"), "owner present")
plugins = m.get("plugins", [])
check(len(plugins) == 3, f"exactly three plugins listed (got {len(plugins)})")

def remote_url(src):
    if src["source"] == "github":
        return f"https://github.com/{src['repo']}"
    return src["url"]

for pl in plugins:
    name = pl.get("name", "<unnamed>")
    for field in ("name", "description", "license", "homepage", "version"):
        check(bool(pl.get(field)), f"{name}: has {field}")
    src = pl.get("source") or {}
    ref, sha = src.get("ref"), src.get("sha")
    check(bool(ref), f"{name}: source pinned to a ref")
    check(bool(sha) and re.fullmatch(r"[0-9a-f]{40}", sha or ""), f"{name}: source pinned to a 40-hex sha")
    if not (ref and sha):
        continue
    out = subprocess.run(
        ["git", "ls-remote", remote_url(src), f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}"],
        capture_output=True, text=True, timeout=120)
    lines = dict(reversed(l.split("\t")) for l in out.stdout.splitlines())
    resolved = lines.get(f"refs/tags/{ref}^{{}}") or lines.get(f"refs/tags/{ref}")
    check(resolved == sha, f"{name}: {ref} on remote resolves to pinned sha (got {resolved})")
    if src["source"] == "git-subdir" and resolved == sha:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "clone", "--depth", "1", "--branch", ref, src["url"], td],
                           check=True, capture_output=True, timeout=300)
            sub = pathlib.Path(td) / src["path"]
            check((sub / ".claude-plugin" / "plugin.json").is_file(),
                  f"{name}: subdir '{src['path']}' holds a plugin manifest at {ref}")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
