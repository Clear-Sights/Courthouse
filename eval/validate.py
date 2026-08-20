#!/usr/bin/env python3
"""Validate the Courthouse marketplace manifest.

Checks, stdlib + git only:
  1. marketplace.json parses and carries the required top-level fields.
  2. Every plugin entry has name, description, license, version, and a pinned
     source (ref + sha, sha 40 hex chars).
  3. Every pinned (repo, ref, sha) actually exists on the remote: the tag or
     release branch is reachable and the commit it resolves to equals the sha.
  4. The declared version appears in the ref that ships it.
  5. The pinned tree really holds a plugin manifest at the entry's path, and the
     version that manifest declares equals the version the entry advertises.

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
    # A ref is a tag OR a release branch. Tags are tried first and peeled -- an annotated tag's
    # own object id is not the commit id -- with refs/heads as the fallback: this account's git
    # credential is scoped to refs/heads/*, and pushing refs/tags/* returns HTTP 403, so a release
    # is pinned as a branch whose head IS the sha. Resolving tags only silently failed every such
    # pin with "got None", which reads as a missing release rather than an unsupported ref kind.
    # The sha is the real pin in both cases; the ref only says where to find it.
    out = subprocess.run(
        ["git", "ls-remote", remote_url(src),
         f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}", f"refs/heads/{ref}"],
        capture_output=True, text=True, timeout=120)
    lines = dict(reversed(l.split("\t")) for l in out.stdout.splitlines())
    resolved = (lines.get(f"refs/tags/{ref}^{{}}") or lines.get(f"refs/tags/{ref}")
                or lines.get(f"refs/heads/{ref}"))
    check(resolved == sha, f"{name}: {ref} on remote resolves to pinned sha (got {resolved})")
    # The declared version must appear in the ref that ships it. `gyroscope` shipped `version:
    # 0.1.0` against `ref: v1.0.0` for the whole v1 series and nothing here noticed, because every
    # other check reads the two fields independently. A marketplace's version is what a consumer
    # pins and what an upgrade compares, so a version naming a release that is not the one it
    # fetches is a wrong answer to the only question the field is asked.
    check(pl.get("version", "") in ref,
          f"{name}: declared version {pl.get('version')!r} appears in ref {ref!r}")
    # Everything above is read from THIS repository, so the fields agree with each other while
    # disagreeing with the plugin they point at. Fetching the pinned tree is the only check that
    # binds this file to what a consumer installs, and both defects it catches had shipped:
    # all three entries named a version their own plugin.json did not declare, and ward/makoto
    # moved the manifest under `plugin/` without the entry following it, so the pinned tree had
    # no manifest where the entry said. One path for every entry -- a source kind that skips the
    # fetch is a source kind whose pin is never actually opened.
    if resolved:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "clone", "--depth", "1", "--branch", ref, remote_url(src), td],
                           check=True, capture_output=True, timeout=300)
            where = src.get("path", "")
            manifest = pathlib.Path(td, where, ".claude-plugin", "plugin.json")
            present = manifest.is_file()
            check(present, f"{name}: plugin manifest present at '{where or '.'}' in {ref}")
            declared = json.loads(manifest.read_text(encoding="utf-8")).get("version") if present else None
            check(declared == pl.get("version"),
                  f"{name}: plugin at {ref} declares {declared!r}, entry says {pl.get('version')!r}")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
