#!/usr/bin/env python3
"""
Puts the livetv-cloud Worker's "last asked ESPN" times (espn/_state.json) into the espn/*.json
files: the Worker saves a league's file only when its games changed, so the times inside a file
can be older than the last time ESPN was asked and gave the same answer. Same file format as
scripts/espn.py writes. Only the Python standard library is used.
"""
import json
import os
import re

OUT_DIR = "espn"


def safe(lid):
    return re.sub(r"[^a-zA-Z0-9]+", "_", lid)


def main():
    try:
        with open(os.path.join(OUT_DIR, "_state.json"), encoding="utf-8") as f:
            leagues = json.load(f).get("leagues", {})
    except (ValueError, OSError):
        print("No Worker notes: times left as they are.")
        return
    moved = 0
    for lid, info in leagues.items():
        path = os.path.join(OUT_DIR, safe(lid) + ".json")
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (ValueError, OSError):
            continue
        touched = False
        for day, v in doc.get("days", {}).items():
            s = info.get("days", {}).get(day)
            if not s or s.get("at", 0) <= v.get("fetchedAt", 0):
                continue
            v["fetchedAt"] = s["at"]
            v["liveOrSoon"] = bool(s.get("live"))
            touched = True
        text = json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        moved += touched
    print("Worker's asked-at times put in %d league files." % moved)


if __name__ == "__main__":
    main()
