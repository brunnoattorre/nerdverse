#!/usr/bin/env python3
"""Write an episode page for every new NerdScience, NerdHistory and NerdNature video.

For each channel's newest uploads that have no page yet:
  1. read the video's transcript: a saved copy in .transcripts/<id>.txt (the backfill), or
     the channel's own captions through the YouTube API (YT_CAPTION_TOKENS, one refresh
     token per channel, made with webapp/yt_authorize.py --captions);
  2. Claude (Sonnet 5.5, with web search) writes the breakdown: every fight, who won and
     why, explained the way the video decides it;
  3. a second Claude pass fact-checks every canon and real-world claim with web search,
     rewrites what doesn't hold up and keeps the sources;
  4. a third pass finds three related products on Amazon (tag nerdscience-20).
The result is saved to episodes/<channel>/<videoId>.json; render_episodes.py turns those
into pages. A video without a transcript is skipped and retried on the next run.

    python3 episodes.py                      # new videos on every channel (daily job)
    python3 episodes.py --backfill 10        # the 10 newest per channel
    python3 episodes.py --only hKCmxUGFzok   # one video, even if it already has a page
    python3 episodes.py --max-new 3          # cap new pages per channel per run
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import anthropic

import build  # CHANNELS, is_compilation, SSL context

HERE = Path(__file__).parent
DATA = HERE / "episodes"
TRANSCRIPTS = HERE / ".transcripts"
SLUGS = {"science": "nerdscience", "history": "nerdhistory", "nature": "nerdnature"}
MODEL = os.environ.get("EPISODE_MODEL", "claude-sonnet-5-5")
AMAZON_TAG = "nerdscience-20"
MIN_SECONDS = 240  # anything shorter is a Short or a teaser, not an episode
MAX_RESUMES = 8

WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 12},
    {"type": "web_fetch_20260318", "name": "web_fetch", "max_uses": 6, "max_content_tokens": 15000},
]
AMAZON_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 8,
     "allowed_domains": ["amazon.com"]},
]


# ── YouTube ───────────────────────────────────────────────────────────────────

def _api(path, params, token=None):
    url = f"https://www.googleapis.com/youtube/v3/{path}?{urllib.parse.urlencode(params)}"
    headers = dict(build.UA)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30,
                                context=build.SSL) as r:
        return r.read().decode("utf-8", "replace")


def _seconds(iso):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def recent_videos(ch, n):
    """The channel's n newest public episodes (no Shorts, no compilations), newest first."""
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        sys.exit("YOUTUBE_API_KEY is not set")
    uploads = "UU" + ch["id"][2:]
    items = json.loads(_api("playlistItems", {"part": "contentDetails", "playlistId": uploads,
                                              "maxResults": 50, "key": key})).get("items", [])
    ids = [it["contentDetails"]["videoId"] for it in items]
    if not ids:
        return []
    vids = json.loads(_api("videos", {"part": "snippet,contentDetails,status", "id": ",".join(ids),
                                      "key": key})).get("items", [])
    out = []
    for v in vids:
        sn = v["snippet"]
        if v.get("status", {}).get("privacyStatus") != "public":
            continue
        if build.is_compilation(sn["title"]) or _seconds(v["contentDetails"]["duration"]) < MIN_SECONDS:
            continue
        out.append({"id": v["id"], "title": sn["title"], "description": sn.get("description", ""),
                    "published": sn["publishedAt"], "duration": v["contentDetails"]["duration"],
                    "tags": sn.get("tags", [])})
    out.sort(key=lambda v: v["published"], reverse=True)
    return out[:n]


def _caption_token(channel_name):
    raw = os.environ.get("YT_CAPTION_TOKENS", "").strip()
    cid, secret = os.environ.get("YT_OAUTH_CLIENT_ID"), os.environ.get("YT_OAUTH_CLIENT_SECRET")
    if not (raw and cid and secret):
        return None
    refresh = json.loads(raw).get(channel_name)
    if not refresh:
        return None
    body = urllib.parse.urlencode({"client_id": cid, "client_secret": secret,
                                   "refresh_token": refresh, "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=body),
                                timeout=30, context=build.SSL) as r:
        return json.loads(r.read())["access_token"]


def _srt_to_text(srt):
    lines = []
    for block in re.split(r"\n\s*\n", srt.strip()):
        rows = block.strip().splitlines()
        if len(rows) >= 3 and "-->" in rows[1]:
            start = rows[1].split("-->")[0].strip()
            h, m, s = start.replace(",", ".").split(":")
            t = int(h) * 3600 + int(m) * 60 + int(float(s))
            lines.append(f"[{t // 60:02d}:{t % 60:02d}] " + " ".join(rows[2:]))
    return "\n".join(lines)


def transcript(video, channel_name):
    saved = TRANSCRIPTS / f"{video['id']}.txt"
    if saved.exists() and saved.stat().st_size > 500:
        return saved.read_text()
    token = _caption_token(channel_name)
    if not token:
        return None
    tracks = json.loads(_api("captions", {"part": "snippet", "videoId": video["id"]}, token)).get("items", [])
    en = [t for t in tracks if t["snippet"]["language"].startswith("en")]
    if not en:
        return None
    en.sort(key=lambda t: t["snippet"]["trackKind"] == "asr")  # a hand-made track first
    srt = _api(f"captions/{en[0]['id']}", {"tfmt": "srt"}, token)
    text = _srt_to_text(srt)
    if len(text) < 500:
        return None
    TRANSCRIPTS.mkdir(exist_ok=True)
    saved.write_text(text)
    return text


# ── Claude ────────────────────────────────────────────────────────────────────

_client = None


def _claude():
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            sys.exit("ANTHROPIC_KEY is not set")
        _client = anthropic.Anthropic(api_key=key, timeout=900)
    return _client


def _turn(system, user, tools=None, max_tokens=32000, label="call"):
    """One turn to completion, resuming across pause_turn; returns (text, searches)."""
    messages = [{"role": "user", "content": user}]
    parts, searches = [], 0
    usage = {"in": 0, "out": 0}
    for _ in range(MAX_RESUMES + 1):
        kwargs = {"tools": tools} if tools else {}
        with _claude().messages.stream(model=MODEL, max_tokens=max_tokens, system=system,
                                       thinking={"type": "adaptive"}, messages=messages,
                                       **kwargs) as stream:
            resp = stream.get_final_message()
        parts.append("".join(b.text for b in resp.content if b.type == "text"))
        stu = getattr(resp.usage, "server_tool_use", None)
        searches += getattr(stu, "web_search_requests", 0) or 0
        usage["in"] += resp.usage.input_tokens or 0
        usage["out"] += resp.usage.output_tokens or 0
        if resp.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": resp.content}]
    print(f"    {label}: {usage['in']} in / {usage['out']} out tokens, {searches} searches")
    return "".join(parts), searches


def _json(text):
    """The last JSON object in the reply (prose before it, fences around it, are ignored)."""
    text = re.sub(r"```(?:json)?", "", text)
    end = text.rfind("}")
    depth = 0
    for i in range(end, -1, -1):
        depth += text[i] == "}"
        depth -= text[i] == "{"
        if depth == 0:
            return json.loads(text[i:end + 1])
    raise ValueError("no JSON object in the reply")


WRITE_SYSTEM = """\
You write the episode pages for {channel}, a YouTube channel that drops characters, armies or \
animals into impossible fights and scores each one with a survival tier from F to S. Each page \
tells a reader who won every fight in the video and WHY, the way the video decides it. The page \
JUSTIFIES the video's results: it makes the strongest true case for the outcome the video gives. It \
never argues against a result, never says the video got it wrong, never suggests a different \
winner or tier.

Ground rules:
- The transcript is the source of truth for what happens in the video: who fights whom, who \
wins, the tiers, and the mechanism the video uses to decide each fight. Never change an \
outcome, invent a fight, or add an event the video doesn't have.
- The "why" is the point of the page. For each fight, explain the deciding mechanism in plain \
words: the power, weapon, weakness, number or rule that settled it, and the moment it happened. \
Lean on the real canon or real-world fact behind it (a feat from a named film, comic or game; a \
real weapon spec; real biology or history), and use web_search to confirm those facts as you \
write. Name the source work for canon facts ("in Predator 2", "in the 1987 cartoon").
- Write in {channel}'s own voice, as the people who made the episode: state what happened and why \
as fact ("Thor's lightning can't hurt the infected, so...") or as the channel's call ("we score it \
a C because..."), never as a summary of a video. Never write "the video says", "the video notes", \
"the video calls", "the video admits", "the narrator", or mention a transcript, a script or a draft.
- Write like a sharp fan explaining it to a friend: short paragraphs, concrete nouns, no hype \
words, no "In this video", no "Let's dive in". US customary units.
- Some videos are not fights (a history explainer, a "what if"). Then each "fight" is one chapter \
of the video, "winner" is its outcome in a few words, and the "why" explains what decided it.

Answer with ONLY one JSON object, in exactly this shape:
{{"headline": "<page title, max 60 characters, names both sides, e.g. 'TMNT vs Predator: Who Wins and Why'>",
 "meta_description": "<max 155 characters, the question and the answer's angle, no spoilers of the final winner>",
 "dek": "<one sentence, max 28 words, what the video tests>",
 "verdict": "<the overall answer in one line, max 14 words>",
 "fights": [{{"title": "<the chapter's name>", "matchup": "<A vs B>", "winner": "<who won, or the outcome>",
   "tier": "<the survival tier the video gives, F-S, or empty>",
   "why": ["<paragraph>", "<paragraph>"]}}],
 "takeaway": "<one paragraph: what the whole video comes down to>",
 "entities": ["<every named character, army, species, film, game, battle and place that matters>"],
 "search_terms": ["<5-8 phrases a fan would type to find this, e.g. 'tmnt vs predator who would win'>"]}}
2-4 "why" paragraphs per fight, 40-110 words each."""

CHECK_SYSTEM = """\
You are the fact checker for {channel}'s episode pages. You receive a draft page (JSON) and the \
video's transcript. Check every claim in the draft that is true or false outside the video's own \
story: canon facts (what a character, weapon or creature can do, what happened in a named film, \
comic, show or game, who said what), real-world facts (dates, units, weapons and their specs, \
numbers, biology, physics, history). Search for each one with web_search and read the page that \
settles it; do not answer from memory.

The video's own hypothetical events (who wins here, the tiers, what happens in this crossover) \
are not checked and are NEVER changed. The page exists to justify the video's results, not to \
review them: every winner, tier, verdict and outcome stays exactly as the draft has it, and nothing \
you write may argue against them, call them wrong, or suggest another result.

When a supporting fact is wrong, replace it with the true fact that still supports the same \
outcome: the correct feat, number or scene, or another reason the transcript itself gives for that \
result. When a fact cannot be confirmed, keep the point the video makes and drop or soften only the \
unconfirmed detail. A correction makes the case for the result accurate; it must never weaken the \
case or turn it around. Keep the voice and length. Then return the corrected page: the same JSON object as \
the draft, plus two keys:
 "sources": [{{"title": "<page title>", "url": "<url you actually read>", "supports": "<the fact it confirms, short>"}}]  (4-10, only pages that confirmed something on the page)
 "fact_check": {{"checked": <number of claims checked>, "corrected": <number rewritten or cut>,
                 "notes": ["<one line per correction: what the draft said, what is true>"]}}
Answer with ONLY that JSON object."""

AMAZON_SYSTEM = """\
You pick three products for a NerdVerse episode page, from amazon.com, that a viewer of this \
episode would actually want: the comics, films, games, books, figures or gear the episode is \
about (licensed, official products only; no knock-offs, no unrelated bestsellers). Use web_search \
(it only searches amazon.com) to find real product pages and read their ASIN from the URL \
(/dp/XXXXXXXXXX). Prefer items that are in stock and broadly appealing. Never invent an ASIN.

Answer with ONLY one JSON object:
{"products": [{"name": "<product name as Amazon lists it, shortened to max 70 characters>",
  "asin": "<10-character ASIN from the URL>", "kind": "<comic | film | game | book | figure | gear | other>",
  "why": "<max 16 words: why it fits this episode>"}]}"""


VOICE_SYSTEM = """\
You edit {channel}'s episode pages so they read as the channel's own write-up of its episode, not \
as a summary of a video. Find every sentence that narrates the video from the outside: "the video \
says/notes/calls/admits/argues/explains/uses/frames", "the episode says", "the narrator", "in the \
video", "this video", or any mention of a transcript, script or draft. Rewrite each one as a plain statement of \
the fact or as the channel's own call ("we score it a C", "our verdict"), keeping every fact, \
winner, tier and number exactly as it is. Change nothing else.

Answer with ONLY a JSON object: {{"edits": [{{"old": "<exact text from the page, unique>", "new": "<replacement>"}}]}}
Each "old" is copied exactly from one field and occurs once on the page. Return {{"edits": []}} if \
nothing needs changing."""

_META = re.compile(r"\b(the video|this video|the episode (says|notes|calls|admits|argues|explains|uses|frames|"
                   r"states|starts|opens|ends)|the narrator|transcript)\b", re.I)


def voice_pass(page, channel):
    """Rewrite 'the video says…' narration into the channel's own voice. Outcomes stay locked."""
    def fields():
        yield page, "dek"
        yield page, "takeaway"
        for f in page.get("fights", []):
            for i in range(len(f.get("why", []))):
                yield f["why"], i
    done = 0
    for _ in range(2):  # a second pass catches what the first one missed
        if not any(_META.search(str(obj[k])) for obj, k in fields()):
            break
        done += _voice_once(page, channel, fields)
    return done


def _voice_once(page, channel, fields):
    raw, _ = _turn(VOICE_SYSTEM.format(channel=channel), json.dumps(
        {"dek": page.get("dek"), "takeaway": page.get("takeaway"),
         "fights": [{"why": f.get("why", [])} for f in page.get("fights", [])]}, ensure_ascii=False),
        max_tokens=16000, label="voice")
    done = 0
    for ed in _json(raw).get("edits", []):
        old, new = ed.get("old", ""), ed.get("new", "")
        if not old or not new:
            continue
        for obj, k in fields():
            if old in str(obj[k]):
                obj[k] = obj[k].replace(old, new, 1)
                done += 1
                break
    return done


def pick_products(title, channel, page, tries=2):
    """Three Amazon picks; a second search when the first comes back short."""
    who = ", ".join(page.get("entities", [])[:12])
    products = list(page.get("products") or [])
    for _ in range(tries):
        if len(products) >= 3:
            break
        have = ", ".join(p["name"] for p in products) or "none"
        raw, _ = _turn(AMAZON_SYSTEM, f"EPISODE: {title}\nCHANNEL: {channel}\n"
                       f"WHAT IT'S ABOUT: {page.get('dek', '')}\nKEY NAMES: {who}\n"
                       f"ALREADY PICKED (find {3 - len(products)} different ones): {have}",
                       AMAZON_TOOLS, max_tokens=8000, label="amazon picks")
        for p in _json(raw).get("products", []):
            asin = str(p.get("asin", "")).strip().upper()
            if re.fullmatch(r"[A-Z0-9]{10}", asin) and asin not in {x["asin"] for x in products}:
                p["asin"] = asin
                p["url"] = f"https://www.amazon.com/dp/{asin}?tag={AMAZON_TAG}"
                products.append(p)
    return products[:3]


# Channels whose YouTube descriptions get a "Full breakdown" link to their episode page.
LINK_CHANNELS = [c.strip() for c in os.environ.get("DESCRIPTION_LINK_CHANNELS", "NerdScience").split(",") if c.strip()]
SITE_URL = "https://nerdscienceofficial.com"


def _videos_update(token, body):
    req = urllib.request.Request(
        "https://www.googleapis.com/youtube/v3/videos?part=snippet", method="PUT",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30, context=build.SSL) as r:
        return json.loads(r.read())


def link_description(video_id, channel_name, page_path):
    """Add 'Full breakdown and sources: <page>' to the video's description, once.

    It goes after the description's paragraphs and before the chapters (or the hashtags),
    so the keyword-tuned opening, the chapter list and the hashtags stay where they are.
    The title, tags and category are sent back unchanged."""
    if channel_name not in LINK_CHANNELS:
        return "channel not enabled"
    token = _caption_token(channel_name)
    if not token:
        return "no token"
    items = json.loads(_api("videos", {"part": "snippet", "id": video_id}, token)).get("items", [])
    if not items:
        return "video not found"
    sn = items[0]["snippet"]
    desc = sn.get("description", "")
    if "nerdscienceofficial.com" in desc:
        return "already linked"
    line = f"Full breakdown and sources: {SITE_URL}{page_path}"
    lines = desc.split("\n")
    at = next((i for i, l in enumerate(lines) if re.match(r"\s*(0?0:00|0:00)\b", l)), None)
    if at is None:
        at = next((i for i, l in enumerate(lines) if l.strip().startswith("#")), len(lines))
    while at > 0 and not lines[at - 1].strip():
        at -= 1
    # lines[at:] already starts with the blank line that separated paragraphs from chapters
    new = "\n".join(lines[:at] + ["", line] + lines[at:]).strip()
    if len(new) > 5000:
        return "description too long"
    body = {"id": video_id, "snippet": {k: sn[k] for k in ("title", "categoryId", "tags", "defaultLanguage",
                                                          "defaultAudioLanguage") if k in sn}}
    body["snippet"]["description"] = new
    _videos_update(token, body)
    return "linked"


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-+", "-", s)[:70].rstrip("-")


def make_page(video, ch, text):
    name = ch["name"]
    clipped = text if len(text) < 90000 else text[:90000]
    brief = (f"VIDEO TITLE: {video['title']}\nPUBLISHED: {video['published'][:10]}\n\n"
             f"YOUTUBE DESCRIPTION:\n{video['description'][:4000]}\n\nTRANSCRIPT:\n{clipped}")

    raw, s1 = _turn(WRITE_SYSTEM.format(channel=name), brief, WEB_TOOLS, label="write")
    draft = _json(raw)

    page, s2 = None, 0
    for attempt in range(2):  # a check that cites under 4 sources runs once more
        raw, n = _turn(CHECK_SYSTEM.format(channel=name),
                       f"DRAFT PAGE:\n{json.dumps(draft, ensure_ascii=False)}\n\nTRANSCRIPT:\n{clipped}",
                       WEB_TOOLS, label="fact check" + (" (retry)" if attempt else ""))
        got = _json(raw)
        got_n = len([x for x in got.get("sources", []) if str(x.get("url", "")).startswith("http")])
        if page is None or got_n > len(page.get("sources", [])):
            page, s2 = got, n
        if got_n >= 4:
            break
    if not page.get("fights"):
        raise ValueError("fact check returned no fights")
    # The results are the video's, read from the transcript by the writer. The fact check may
    # rewrite the reasons, never the outcomes, so they are put back from the draft in code.
    if len(page["fights"]) != len(draft["fights"]):
        raise ValueError(f"fact check changed the fights ({len(draft['fights'])} -> {len(page['fights'])})")
    for got, orig in zip(page["fights"], draft["fights"]):
        for k in ("title", "matchup", "winner", "tier"):
            if got.get(k) != orig.get(k):
                print(f"    kept the video's {k}: {orig.get(k)!r} (checker had {got.get(k)!r})")
            got[k] = orig.get(k)
    for k in ("verdict", "headline"):
        page[k] = draft.get(k)
    if s2 == 0:
        raise ValueError("fact check ran no searches")
    # Only keep sources the checker could have read: real http(s) URLs.
    page["sources"] = [s for s in page.get("sources", [])
                       if str(s.get("url", "")).startswith(("http://", "https://"))]

    voice_pass(page, name)
    page["products"] = pick_products(video["title"], name, page)

    page.update({
        "video_id": video["id"], "video_title": video["title"], "channel": ch["key"],
        "published": video["published"], "duration": video["duration"],
        "slug": _slug(page.get("headline") or video["title"]),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": MODEL,
    })
    return page


def existing(ch_key):
    folder = DATA / SLUGS[ch_key]
    return {p.stem for p in folder.glob("*.json")} if folder.exists() else set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0, help="look at the N newest videos per channel")
    ap.add_argument("--max-new", type=int, default=3, help="new pages per channel per run")
    ap.add_argument("--only", nargs="*", default=[], help="these video ids only (regenerates them)")
    ap.add_argument("--channel", choices=list(SLUGS), help="one channel only")
    ap.add_argument("--revoice", action="store_true", help="run the voice pass on every saved page")
    ap.add_argument("--link-descriptions", action="store_true",
                    help="add the episode-page link to every saved episode's YouTube description")
    ap.add_argument("--repick", action="store_true", help="re-pick Amazon products where a page has fewer than 3")
    a = ap.parse_args()

    if a.link_descriptions:
        for ch in build.CHANNELS:
            for f in sorted((DATA / SLUGS[ch["key"]]).glob("*.json")):
                page = json.loads(f.read_text())
                try:
                    res = link_description(page["video_id"], ch["name"], f"/{SLUGS[ch['key']]}/{page['slug']}/")
                except Exception as err:
                    res = f"failed: {err}"
                if res != "channel not enabled":
                    print(f"  {ch['name']} {page['video_id']}: {res}")
        return 0

    if a.repick:
        for ch in build.CHANNELS:
            for f in sorted((DATA / SLUGS[ch["key"]]).glob("*.json")):
                page = json.loads(f.read_text())
                if len(page.get("products", [])) >= 3:
                    continue
                page["products"] = pick_products(page["video_title"], ch["name"], page)
                f.write_text(json.dumps(page, ensure_ascii=False, indent=1))
                print(f"  {f.stem}: {len(page['products'])} products")
        return 0

    if a.revoice:
        for ch in build.CHANNELS:
            for f in sorted((DATA / SLUGS[ch["key"]]).glob("*.json")):
                page = json.loads(f.read_text())
                n = voice_pass(page, ch["name"])
                if n:
                    f.write_text(json.dumps(page, ensure_ascii=False, indent=1))
                print(f"  {f.stem}: {n} sentences rewritten")
        return 0

    look = max(a.backfill, 6)
    made = failed = 0
    for ch in build.CHANNELS:
        if a.channel and ch["key"] != a.channel:
            continue
        have = existing(ch["key"])
        vids = recent_videos(ch, look if not a.only else 50)
        if a.only:
            vids = [v for v in vids if v["id"] in a.only]
        else:
            vids = [v for v in vids if v["id"] not in have][: (a.backfill or a.max_new)]
        print(f"{ch['name']}: {len(vids)} to write")
        for v in vids:
            print(f"  {v['id']}  {v['title']}")
            try:
                text = transcript(v, ch["name"])
            except urllib.error.HTTPError as err:
                # 400/401 from the token endpoint: the refresh token was revoked or expired.
                print(f"    caption access failed ({err.code}); if this repeats, re-run "
                      f"webapp/yt_authorize.py --captions for {ch['name']} and update YT_CAPTION_TOKENS")
                text = None
            if not text:
                print("    no transcript yet — will retry next run")
                continue
            try:
                page = make_page(v, ch, text)
            except Exception as e:  # one bad episode must not stop the rest
                print(f"    FAILED: {e}")
                failed += 1
                continue
            out = DATA / SLUGS[ch["key"]] / f"{v['id']}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(page, ensure_ascii=False, indent=1))
            made += 1
            path = f"/{SLUGS[ch['key']]}/{page['slug']}/"
            try:
                print(f"    description: {link_description(v['id'], ch['name'], path)}")
            except Exception as err:  # a description edit must never fail the page
                print(f"    description link failed: {err}")
            print(f"    saved: {len(page['fights'])} fights, {len(page.get('sources', []))} sources, "
                  f"{page.get('fact_check', {}).get('corrected', 0)} corrections, "
                  f"{len(page['products'])} products")
    print(f"done: {made} written, {failed} failed")
    return 1 if failed and not made else 0


if __name__ == "__main__":
    sys.exit(main())
