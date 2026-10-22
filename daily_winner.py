#!/usr/bin/env python3
"""Pick the daily winner of the ideas board and record it in Firestore.

The winner is the approved idea that gained the most votes in the 24 hours before the
run (ties: more total votes, then the older idea). It is written to winners/{YYYY-MM-DD}.
Days with no votes produce no winner.

Runs with Application Default Credentials: in GitHub Actions these come from workload
identity federation (no stored key); locally, `gcloud auth application-default login`.
"""
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

PROJECT = "nerdscience-ideas"


def main():
    from google.cloud import firestore

    db = firestore.Client(project=PROJECT)

    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    if db.collection("winners").document(day).get().exists:
        print(f"{day}: winner already recorded")
        return

    since = now - timedelta(hours=24)
    gained = Counter(v.get("ideaId") for v in
                     db.collection("votes").where("createdAt", ">=", since).stream())
    candidates = []
    for idea_id, n in gained.items():
        snap = db.collection("ideas").document(idea_id).get()
        if snap.exists and snap.get("status") == "approved":
            d = snap.to_dict()
            candidates.append((n, d.get("votes", 0), -d["createdAt"].timestamp(), idea_id, d))
    if not candidates:
        print(f"{day}: no votes in the last 24h, no winner")
        return

    n, total, _, idea_id, d = max(candidates)
    db.collection("winners").document(day).set({
        "day": day, "ideaId": idea_id, "title": d["title"], "channel": d.get("channel"),
        "authorName": d.get("authorName", ""), "gained": n, "total": total,
        "decidedAt": firestore.SERVER_TIMESTAMP,
    })
    print(f"{day}: winner {d['title']!r} (+{n} today, {total} total)")


if __name__ == "__main__":
    sys.exit(main())
