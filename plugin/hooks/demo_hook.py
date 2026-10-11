#!/usr/bin/env python3
"""The hook edge of demo mode: surface what the judges did, at the moment they do it.

This is the only part of the mode that runs unattended, so its entire job is to be harmless.
It rules on nothing, it never denies, and it returns the empty object on every path that is not
"the mode is on AND a judge fired since the last event". A demo feature that can block a tool
call, or raise where the host reads a verdict, is a strictly worse thing than no demo at all.

It emits `systemMessage`, which the host shows the user. Hook stderr on a successful exit reaches
the debug log and nobody else -- the same fact `docs/FAIL-DIRECTION.md` records for the engines'
fail-open notices -- so stderr would make this mode invisible, which is the one thing it cannot be.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def main() -> int:
    try:
        sys.stdin.read()  # drained so the writer never blocks; the payload is not needed
    except Exception:  # noqa: BLE001
        pass
    try:
        from courthouse.demo import mode_is_on, unseen

        if not mode_is_on():
            print("{}")
            return 0
        fired = unseen()
        if fired:
            body = "\n".join("  " + activity.line()[:200] for activity in fired)
            print(json.dumps({"systemMessage":
                              f"courthouse demo -- the bench just acted:\n{body}"}))
        else:
            print("{}")
    except Exception:  # noqa: BLE001 -- never let the window break the session it watches
        print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
