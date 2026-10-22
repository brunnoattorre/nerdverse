#!/usr/bin/env python3
"""Track the ideas board's Idea of the Month. Runs daily from the site workflow.

Every run:
  - writes standings/current: this month's top 3 by votes gained since the 1st (UTC);
  - if last month has no winner yet, picks it and writes winners/{YYYY-MM}.
    Normally that happens on the 1st; a missed run catches up on the next one.

The winner is the approved idea that gained the most votes during the month (ties: more
total votes, then the older idea). A vote counts in the month it was cast; removed votes
don't count. Months with no votes produce no winner.

Runs with Application Default Credentials: in GitHub Actions these come from workload
identity federation (no stored key); locally, `gcloud auth application-default login`.
"""
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

PROJECT = "nerdscience-ideas"


def month_start(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def ranked(db, start, end):
    """Approved ideas by votes gained in [start, end), best first."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    q = (db.collection("votes").where(filter=FieldFilter("createdAt", ">=", start))
         .where(filter=FieldFilter("createdAt", "<", end)))
    gained = Counter(v.get("ideaId") for v in q.stream())
    rows = []
    for idea_id, n in gained.items():
        snap = db.collection("ideas").document(idea_id).get()
        if snap.exists and snap.get("status") == "approved":
            d = snap.to_dict()
            rows.append((n, d.get("votes", 0), -d["createdAt"].timestamp(), idea_id, d))
    rows.sort(reverse=True)
    return [{"ideaId": idea_id, "title": d["title"], "channel": d.get("channel"),
             "authorName": d.get("authorName", ""), "gained": n, "total": total}
            for n, total, _, idea_id, d in rows]


def main():
    from google.cloud import firestore

    db = firestore.Client(project=PROJECT)
    now = datetime.now(timezone.utc)
    this_month = month_start(now)
    last_month = month_start(this_month - timedelta(days=1))

    key = last_month.strftime("%Y-%m")
    ref = db.collection("winners").document(key)
    if not ref.get().exists:
        top = ranked(db, last_month, this_month)
        if top:
            ref.set({**top[0], "month": key, "decidedAt": firestore.SERVER_TIMESTAMP})
            print(f"{key}: winner {top[0]['title']!r} (+{top[0]['gained']} that month)")
        else:
            print(f"{key}: no votes that month, no winner")

    leaders = ranked(db, this_month, now)[:3]
    db.collection("standings").document("current").set({
        "month": this_month.strftime("%Y-%m"), "leaders": leaders,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    print(f"{this_month:%Y-%m} so far: " + (", ".join(f"{l['title']!r} +{l['gained']}" for l in leaders) or "no votes yet"))


if __name__ == "__main__":
    sys.exit(main())
