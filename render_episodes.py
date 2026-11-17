#!/usr/bin/env python3
"""Render the episode pages from episodes/<channel>/<videoId>.json (written by episodes.py).

  /<channel>/                 the archive: every episode, a search box, every name that has fought
  /<channel>/<slug>/          one episode: the embedded video, every fight and why it went that way,
                              the sources it was checked against, three Amazon picks

Also returns the page list so build.py can put every URL in sitemap.xml.

    python3 render_episodes.py
"""
import html
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import build

HERE = Path(__file__).parent
DATA = HERE / "episodes"
SITE = build.SITE
SLUGS = {"science": "nerdscience", "history": "nerdhistory", "nature": "nerdnature"}
# The channel's question, with the newest episode's thumbnail set inside it where the name goes.
QUESTION = {"science": ("Could", "survive?"), "history": ("Could", "hold?"),
            "nature": ("Could", "survive?")}
LEDES = {
    "science": "Every NerdScience episode, fight by fight: who won, and the canon that decided it, "
               "checked against the films, comics and games.",
    "history": "Every NerdHistory episode, battle by battle: who held, who broke, and the real "
               "history and weapons that decided it.",
    "nature": "Every NerdNature episode, fight by fight: who won, and the real anatomy and biology "
              "that decided it.",
}
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Bangers&family=Barlow:wght@500;700;800'
         '&display=swap" rel="stylesheet">')
REVEAL_JS = """<script>
document.documentElement.classList.remove('no-js');
(function(){var els=document.querySelectorAll('.rise');
if(!('IntersectionObserver' in window)){els.forEach(function(e){e.classList.add('in')});return}
var io=new IntersectionObserver(function(es){es.forEach(function(en){if(en.isIntersecting){
var kids=en.target.parentElement.querySelectorAll('.rise');var i=Array.prototype.indexOf.call(kids,en.target);
setTimeout(function(){en.target.classList.add('in')},Math.min(Math.max(0,i),4)*75);io.unobserve(en.target)}})},{rootMargin:'0px 0px -8% 0px'});
els.forEach(function(e){io.observe(e)})})();
</script>"""

e = html.escape
# Changes with the stylesheet, so browsers never keep an old copy after a deploy.
CSS_VER = __import__("hashlib").md5((HERE / "assets" / "episodes.css").read_bytes()).hexdigest()[:8]


def thumb(vid, size="hqdefault"):
    return f"https://i.ytimg.com/vi/{vid}/{size}.jpg"


def load():
    eps = defaultdict(list)
    for key, slug in SLUGS.items():
        for p in sorted((DATA / slug).glob("*.json")):
            d = json.loads(p.read_text())
            d["url"] = f"{SITE}{slug}/{d['slug']}/"
            d["path"] = f"/{slug}/{d['slug']}/"
            eps[key].append(d)
        eps[key].sort(key=lambda d: d["published"], reverse=True)
    return eps


def nav(current=None):
    links = "".join(
        f'<li><a href="/{SLUGS[c["key"]]}/"{" aria-current=page" if c["key"] == current else ""}>{c["name"]}</a></li>'
        for c in build.CHANNELS)
    return (f'<nav class="nav" aria-label="Main"><div class="wrap"><a class="brand" href="/">NerdVerse</a>'
            f'<ul>{links}<li><a href="/ideas/">Ideas</a></li><li><a href="{build.STORE}">Store</a></li></ul>'
            f'</div></nav>')


def foot():
    chans = "".join(f'<li><a href="https://www.youtube.com/@{c["handle"]}">{c["name"]} on YouTube</a></li>'
                    for c in build.CHANNELS)
    return f'''<footer class="foot"><div class="wrap">
<div class="foot-top"><div><h2>Pick the next fight</h2><a class="btn" href="/ideas/">Submit and vote</a></div>
<ul>{chans}<li><a href="{build.STORE}">Store</a></li></ul></div>
<div class="legal"><span>NerdVerse is independent and not affiliated with Marvel, DC, Paramount, Disney, Toho or any other rights holder. As an Amazon Associate we earn from qualifying purchases.</span>
<span>&copy; {datetime.now():%Y} NerdScience</span></div>
<div class="name" aria-hidden="true">NERDVERSE</div></div></footer>'''


def head(title, desc, url, image, jsonld, extra=""):
    return f'''<!doctype html>
<html lang="en" class="no-js">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="{extra or 'website'}">
<meta property="og:site_name" content="NerdScience">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{image}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{image}">
<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<meta name="theme-color" content="#141414">
{FONTS}
<link rel="stylesheet" href="/assets/episodes.css?v={CSS_VER}">
</head>'''


def clean_title(t):
    """'Chapter 2: The Sewer Hunt' -> 'The Sewer Hunt': the order is the page's, not a label."""
    return re.sub(r"^\s*(chapter|part|round|act)\s*\w+\s*[:.\-–—]\s*|^\s*cold open\s*[:.\-–—]\s*", "",
                  t, flags=re.I) or t


# Amazon only allows product images that come from its Product Advertising API (the old
# SiteStripe image widget now answers 503). Until the account has API access, a pick has no
# "image" and its card shows the product type as a printed label instead.


def _fresh_images():
    """Amazon product photos fetched in the last 24 hours (Amazon's caching limit)."""
    f = DATA / "product_images.json"
    if not f.exists():
        return {}
    now = datetime.utcnow()
    return {a: v["url"] for a, v in json.loads(f.read_text()).items()
            if (now - datetime.strptime(v["fetched"], "%Y-%m-%dT%H:%M:%SZ")).total_seconds() < 86400}


IMAGES = _fresh_images()


def pick_visual(p):
    p = dict(p, image=p.get("image") or IMAGES.get(p.get("asin")))
    if p.get("image"):
        return (f'<span class="pick-img"><img src="{e(p["image"])}" width="250" height="250" '
                f'alt="{e(p["name"])}" loading="lazy"></span>')
    return f'<span class="pick-img label" aria-hidden="true">{e((p.get("kind") or "pick").upper())}</span>'


def pick_card(p, i):
    side = "left" if i % 2 == 0 else "right"
    return f'''<aside class="pick {side}"><div class="wrap"><a class="pick-card rise" href="{e(p["url"])}" rel="sponsored nofollow noopener" target="_blank">
{pick_visual(p)}
<span class="pick-text"><strong>{e(p["name"])}</strong><span class="pick-why">{e(p.get("why", ""))}</span>
<span class="go">See it on Amazon</span><span class="paid">Paid link: we earn from qualifying purchases.</span></span></a></div></aside>'''


def short_date(iso):
    return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%b %-d, %Y")


def org_ref():
    return {"@id": f"{SITE}#org"}


def video_ld(d):
    return {"@type": "VideoObject", "name": d["video_title"], "description": d.get("dek") or d["video_title"],
            "thumbnailUrl": [thumb(d["video_id"], "maxresdefault"), thumb(d["video_id"])],
            "uploadDate": d["published"], "duration": d["duration"],
            "embedUrl": f"https://www.youtube.com/embed/{d['video_id']}",
            "contentUrl": f"https://www.youtube.com/watch?v={d['video_id']}", "publisher": org_ref()}


# ── Episode page ──────────────────────────────────────────────────────────────

def episode_page(d, ch, siblings):
    key = ch["key"]
    title = d.get("headline") or d["video_title"]
    fights = []
    for f in d.get("fights", []):
        tier = (f.get("tier") or "").strip().upper()[:2]
        tier_html = f'<div class="tier" aria-label="Survival tier {e(tier)}">{e(tier)}</div>' if tier else ""
        paras = "".join(f'<p class="rise">{e(p)}</p>' for p in f.get("why", []))
        fights.append(f'''<section class="fight"><div class="wrap fight-grid">
<div><h2 class="rise">{e(clean_title(f.get("title", "")))}</h2>
<div class="score rise">{tier_html}<p class="who">{e(f.get("winner", ""))}<span>{e(f.get("matchup", ""))}</span></p></div></div>
<div class="why">{paras}</div></div></section>''')

    # The three Amazon picks are spread through the page: after the first fight, in the middle,
    # and after the last, alternating sides, so each sits next to the part of the story it fits.
    picks = [pick_card(p, i) for i, p in enumerate(d.get("products", [])[:3])]
    n = len(fights)
    slots = sorted({0, n // 2, max(n - 1, 0)}) if n else []
    woven = []
    for i, block in enumerate(fights):
        woven.append(block)
        if picks and i in slots:
            woven.append(picks.pop(0))
    woven.extend(picks)  # fewer fights than picks: the rest follow the last one

    srcs = "".join(f'<li><a href="{e(s["url"])}" rel="noopener" target="_blank">{e(s.get("title") or s["url"])}</a>'
                   f'<span>{e(s.get("supports", ""))}</span></li>' for s in d.get("sources", []))
    fc = d.get("fact_check", {})
    checked = f'''<section class="checked" id="sources"><div class="wrap checked-grid">
<div><h2 class="rise">How we checked it</h2>
<p class="stat rise">Every canon and real-world claim on this page was searched and read at the source before it went up. These are the pages we read.</p></div>
<ul class="sources rise">{srcs}</ul></div></section>'''

    more = "".join(f'<a class="card" href="{s["path"]}"><img src="{thumb(s["video_id"])}" width="480" height="360" alt="{e(s["video_title"])}" loading="lazy"><span>{e(s.get("headline") or s["video_title"])}</span></a>'
                   for s in siblings[:4])
    more_html = (f'<section class="more"><div class="wrap"><h2 class="rise">More from {ch["name"]}</h2>'
                 f'<div class="more-grid">{more}</div></div></section>') if more else ""

    archive = f"{SITE}{SLUGS[key]}/"
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "BlogPosting", "headline": title, "description": d.get("meta_description", ""),
         "url": d["url"], "datePublished": d["published"], "dateModified": d.get("generated", d["published"]),
         "image": thumb(d["video_id"], "maxresdefault"), "author": org_ref(), "publisher": org_ref(),
         "about": [{"@type": "Thing", "name": n} for n in d.get("entities", [])[:12]],
         "keywords": ", ".join(d.get("search_terms", [])), "video": video_ld(d),
         "isPartOf": {"@type": "CollectionPage", "url": archive}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "NerdVerse", "item": SITE},
            {"@type": "ListItem", "position": 2, "name": f"{ch['name']} episodes", "item": archive},
            {"@type": "ListItem", "position": 3, "name": title, "item": d["url"]}]}]}

    body = f'''<body class="{key}">
{nav(key)}
<main>
<header class="ep-hero"><div class="wrap">
<h1>{e(title)}</h1>
<p class="dek">{e(d.get("dek", ""))}</p>
<div class="screen"><iframe src="https://www.youtube-nocookie.com/embed/{d["video_id"]}?rel=0" title="{e(d["video_title"])}" loading="lazy" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe></div>
<div class="after"><p class="answer">{e(d.get("verdict", ""))}</p>
<a class="btn" href="/{SLUGS[key]}/">Every {ch["name"]} fight</a></div>
</div></header>
{"".join(woven)}
<section class="bottom-line"><div class="wrap"><h2 class="rise">What it comes down to</h2><blockquote class="rise">{e(d.get("takeaway", ""))}</blockquote></div></section>
{checked}
{more_html}
</main>
{foot()}
{REVEAL_JS}
</body></html>'''
    return head(f"{title} | {ch['name']}", d.get("meta_description", d.get("dek", "")), d["url"],
                thumb(d["video_id"], "maxresdefault"), ld, "article") + body


# ── Archive page ──────────────────────────────────────────────────────────────

def ep_card(d, size):
    hay = " ".join([d["video_title"], d.get("headline", ""), d.get("verdict", "")] + d.get("entities", [])).lower()
    img = thumb(d["video_id"], "sddefault")
    return f'''<a class="ep {size}{' rise' if size != 'lead' else ''}" href="{d["path"]}" data-q="{e(hay)}">
<span class="ep-pic"><img src="{img}" width="640" height="480" alt="{e(d["video_title"])}"{' loading="lazy"' if size != "lead" else ""}></span>
<span class="ep-body"><span class="ep-title">{e(d.get("headline") or d["video_title"])}</span>
<span class="ep-verdict">{e(d.get("verdict", ""))}</span>
<span class="ep-date">{short_date(d["published"])}</span></span></a>'''


def archive_page(ch, eps):
    key, slug = ch["key"], SLUGS[ch["key"]]
    url = f"{SITE}{slug}/"
    lead = ep_card(eps[0], "lead") if eps else ""
    grid = "".join(ep_card(d, "small") for d in eps[1:])
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": f"{ch['name']} episodes",
          "url": url, "description": LEDES[key], "isPartOf": {"@id": f"{SITE}#site"}, "publisher": org_ref(),
          "mainEntity": {"@type": "ItemList", "itemListElement": [
              {"@type": "ListItem", "position": i + 1, "url": d["url"], "name": d.get("headline") or d["video_title"]}
              for i, d in enumerate(eps)]}}

    body = f'''<body class="{key}">
{nav(key)}
<main>
<header class="arc-hero"><div class="wrap arc-grid">
<div><h1>Every {ch["name"]} fight, explained</h1>
<p class="lede">{e(LEDES[key])}</p>
<form class="finder" role="search" action="" onsubmit="return false">
<label for="q">Find a fight</label>
<input id="q" name="q" type="search" placeholder="Batman, Spartans, T. rex…" autocomplete="off">
</form>
<p class="count" id="count" aria-live="polite">{len(eps)} episodes</p>
<a class="btn" href="#episodes">Browse every episode</a></div>
<div class="lead-slot"><p class="lead-label">Newest verdict</p>{lead}</div>
</div></header>
<section class="eps" id="episodes" aria-labelledby="h-eps"><div class="wrap">
<h2 id="h-eps" class="rise">All {ch["name"]} episodes</h2>
<div class="ep-grid" id="grid">{grid}</div>
<p class="empty" id="empty" hidden>No episode matches that yet. <a href="/ideas/">Suggest it as the next fight.</a></p>
</div></section>
<section class="how"><div class="wrap how-grid">
<img class="how-logo rise" src="/assets/logo-{key}.jpg" width="400" height="400" alt="{ch["name"]} logo">
<div><h2 class="rise">How a verdict is made</h2>
<p class="rise">{e(ch["about"])}</p>
<p class="rise">Each page is written from the episode itself, then every canon and real-world claim on it is searched and read at the source before it goes up. The winners are the video's; the page shows why.</p>
<a class="btn rise" href="https://www.youtube.com/@{ch["handle"]}?sub_confirmation=1">Subscribe on YouTube</a></div>
</div></section>
</main>
{foot()}
<script>
(function(){{var q=document.getElementById('q'),cards=[].slice.call(document.querySelectorAll('[data-q]')),
c=document.getElementById('count'),empty=document.getElementById('empty');
function run(){{var t=q.value.trim().toLowerCase(),n=0;cards.forEach(function(r){{var ok=!t||r.dataset.q.indexOf(t)>-1;r.hidden=!ok;if(ok)n++}});
c.textContent=t?(n+' of '+cards.length+' episodes match'):(cards.length+' episodes');empty.hidden=n>0;
if(t)history.replaceState(null,'','?q='+encodeURIComponent(q.value.trim()));else history.replaceState(null,'',location.pathname)}}
q.addEventListener('input',run);var p=new URLSearchParams(location.search).get('q');if(p){{q.value=p;run()}}}})();
</script>
{REVEAL_JS}
</body></html>'''
    title = f"{ch['name']} Episodes: Every Fight and Why the Winner Won"
    return head(title, LEDES[key][:155], url, f"{SITE}assets/og.jpg?v=2", ld) + body


def render():
    eps = load()
    pages = []
    for ch in build.CHANNELS:
        key, slug = ch["key"], SLUGS[ch["key"]]
        lst = eps[key]
        out = HERE / slug
        out.mkdir(exist_ok=True)
        (out / "index.html").write_text(archive_page(ch, lst))
        pages.append((f"{SITE}{slug}/", lst[0]["published"][:10] if lst else None))
        live = {d["slug"] for d in lst}
        for d in lst:
            sib = [s for s in lst if s is not d]
            (out / d["slug"]).mkdir(exist_ok=True)
            (out / d["slug"] / "index.html").write_text(episode_page(d, ch, sib))
            pages.append((d["url"], d.get("generated", d["published"])[:10]))
        for old in out.iterdir():  # a page whose JSON was removed
            if old.is_dir() and old.name not in live:
                for f in old.iterdir():
                    f.unlink()
                old.rmdir()
    print(f"rendered {sum(len(v) for v in eps.values())} episode pages and {len(build.CHANNELS)} archives")
    return pages


if __name__ == "__main__":
    render()
