#!/usr/bin/env python3
"""Build the NerdVerse site: fetch each channel's 3 newest uploads, then render index.html.

Run it on a schedule (cron, CI) and the page always shows the latest videos:
    python3 build.py            # fetch + render
    python3 build.py --offline  # render from the last fetch in latest.json

Sources, in order: the YouTube Data API when YOUTUBE_API_KEY is set (reliable from CI
servers), then the channel's /videos tab, then the RSS feed (YouTube serves it 404/500
at random). Shorts are skipped. If every source fails, the previous run's videos are kept.
"""
import html
import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "latest.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
SITE = "https://nerdscienceofficial.com/"
STORE = "https://nerdscience-official.myspreadshop.com"
IMG = "https://image.spreadshirtmedia.com/image-server/v1"

CHANNELS = [
    {"key": "science", "name": "NerdScience", "handle": "NerdScienceOfficial",
     "id": "UC-cwOu5UYWoC85vX9e-YvGQ", "tagline": "Comics, movies and games",
     "about": "Superheroes, villains and video game legends, tested against each other "
              "and against their own canon. Could Wolverine survive every Superman villain? "
              "Could Kratos solo Game of Thrones? We pull the feats from the source "
              "material and do the maths."},
    {"key": "history", "name": "NerdHistory", "handle": "NerdHistoryNs",
     "id": "UCcdDEmIIb0evR08JWrm7YNA", "tagline": "Real armies, real battles",
     "about": "The greatest fighting forces in history, dropped into battles they never "
              "fought. 300 Spartans at the Alamo, a Navy SEAL team inside Modern Warfare, "
              "the Roman Empire in A Quiet Place. Real units, real weapons, real tactics."},
    {"key": "nature", "name": "NerdNature", "handle": "NerdNatureNs",
     "id": "UCK-9SFPAbWAQfzCUQOWX-7Q", "tagline": "Nature is stranger than fiction",
     "about": "Apex predators, extinct giants and animals scaled up to impossible sizes. "
              "What if house cats were the size of tigers? Which predator could take down "
              "a Xenomorph? Real anatomy and real biology decide every fight."},
]

DESIGN = "/nerd+science+logo?idea=699a0aa41499ed59b83f9695"
PRODUCTS = [  # all from the Nerd Science Logo design
    ("Nerd Science Logo", "Men's premium T-shirt", "$26.99",
     "/nerd+science+logo-A699a0aa41499ed59b83f9695?productType=812&sellable=G7JjB95a1VU7k8VG5Dvr-812-7&appearance=2",
     "/products/T812A2PA4267PT17X220Y72D1058430669W8299H8600/views/1,width=500,height=500,appearanceId=2/nerd-science-logo-mens-premium-t-shirt.jpg"),
    ("Nerd Science Logo", "Women's T-shirt", "$23.49",
     "/nerd+science+logo-A699a0aa41499ed59b83f9695?productType=347&sellable=G7JjB95a1VU7k8VG5Dvr-347-8&appearance=2",
     "/products/T347A2PA4306PT17X38Y30D1058430669W17598H18235/views/1,width=500,height=500,appearanceId=2/nerd-science-logo-womens-t-shirt.jpg"),
    ("Nerd Science Logo", "Men's hoodie", "$41.49",
     "/nerd+science+logo-A699a0aa41499ed59b83f9695?productType=111&sellable=G7JjB95a1VU7k8VG5Dvr-111-22&appearance=2",
     "/products/T111A2PA4247PT17X231Y34D1058430669W10599H10983/views/1,width=500,height=500,appearanceId=2/nerd-science-logo-mens-hoodie.jpg"),
    ("Nerd Science Logo", "Women's hoodie", "$41.49",
     "/nerd+science+logo-A699a0aa41499ed59b83f9695?productType=405&sellable=G7JjB95a1VU7k8VG5Dvr-405-23&appearance=2",
     "/products/T405A2PA4081PT17X61Y21D1058430669W18856H19538/views/1,width=500,height=500,appearanceId=2/nerd-science-logo-womens-hoodie.jpg"),
    ("Nerd Science Logo", "Crewneck sweatshirt", "$37.99",
     "/nerd+science+logo-A699a0aa41499ed59b83f9695?productType=512&sellable=G7JjB95a1VU7k8VG5Dvr-512-27&appearance=2",
     "/products/T512A2PA4049PT17X42Y30D1058430669W21652H22436/views/1,width=500,height=500,appearanceId=2/nerd-science-logo-unisex-crewneck-sweatshirt.jpg"),
    ("Nerd Science Logo", "Contrast coffee mug", "$17.49",
     "/nerd+science+logo-A699a0aa41499ed59b83f9695?productType=268&sellable=G7JjB95a1VU7k8VG5Dvr-268-32&appearance=70",
     "/products/T268A70PA5007PT10X9Y10D1058430669W4213H4365/views/3,width=500,height=500,appearanceId=70/nerd-science-logo-contrast-coffee-mug.jpg"),
    ("Nerd Science Logo", "Tote bag", "$17.99",
     "/nerd+science+logo-A699a0aa41499ed59b83f9695?productType=842&sellable=G7JjB95a1VU7k8VG5Dvr-842-33&appearance=2",
     "/products/T842A2PA3667PT17X38Y29D1058430669W17573H18209/views/1,width=500,height=500,appearanceId=2/nerd-science-logo-tote-bag.jpg"),
    ("Nerd Science Logo", "20 oz water bottle", "$20.99",
     "/nerd+science+logo-A699a0aa41499ed59b83f9695?productType=757&sellable=G7JjB95a1VU7k8VG5Dvr-757-39&appearance=1",
     "/products/T757A1PA4077PT10X9Y9D1058430669W4209H4362/views/3,width=500,height=500,appearanceId=1/nerd-science-logo-20-oz-water-bottle.jpg"),
]


# ── Fetching ────────────────────────────────────────────────────────────────

try:  # python.org macOS builds ship without CA certs; certifi fills the gap when installed
    import certifi
    SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL = ssl.create_default_context()


def get(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=SSL) as r:
        return r.read().decode("utf-8", "replace")


def oembed_title(vid):
    data = json.loads(get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"))
    return data["title"]


def from_api(ch, n=3):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY not set")
    # UULF… is the channel's long-form uploads playlist (no Shorts); UU… is all uploads
    for prefix in ("UULF", "UU"):
        url = ("https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=10"
               f"&playlistId={prefix}{ch['id'][2:]}&key={key}")
        try:
            items = json.loads(get(url))["items"]
        except Exception:
            continue
        out = []
        for it in items:
            sn = it["snippet"]
            if sn["title"] in ("Private video", "Deleted video"):
                continue
            th = sn.get("thumbnails", {})
            best = (th.get("maxres") or th.get("standard") or th.get("high") or {}).get("url")
            vid = sn["resourceId"]["videoId"]
            out.append({"id": vid, "title": sn["title"],
                        "thumb": best or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"})
            if len(out) == n:
                return out
    raise RuntimeError("API returned no usable playlist")


def from_videos_tab(ch, n=3):
    page = get(f"https://www.youtube.com/@{ch['handle']}/videos")
    ids = []
    for vid in re.findall(r'"videoId":"([\w-]{11})"', page):
        if vid not in ids:
            ids.append(vid)
        if len(ids) == n:
            break
    return [{"id": v, "title": oembed_title(v)} for v in ids]


def from_rss(ch, n=3):
    feed = get(f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['id']}")
    out = []
    for entry in re.findall(r"<entry>(.*?)</entry>", feed, re.S):
        link = re.search(r'<link rel="alternate" href="([^"]+)"', entry).group(1)
        if "/shorts/" in link:
            continue
        out.append({"id": re.search(r"<yt:videoId>(.*?)<", entry).group(1),
                    "title": html.unescape(re.search(r"<title>(.*?)<", entry).group(1)),
                    "date": re.search(r"<published>(.*?)<", entry).group(1)[:10]})
        if len(out) == n:
            break
    return out


def thumb_url(vid):
    # maxres exists for most uploads; hq (with letterbox bars, cropped by CSS) always does
    url = f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg"
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=UA), timeout=10, context=SSL)
        return url
    except Exception:
        return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"


def fetch_all(previous):
    result = {}
    for ch in CHANNELS:
        vids = []
        for source in (from_api, from_videos_tab, from_rss):
            try:
                vids = source(ch)
                if len(vids) == 3:
                    break
            except Exception as e:
                print(f"  {ch['name']}: {source.__name__} failed: {e}", file=sys.stderr)
        if len(vids) < 3:
            print(f"  {ch['name']}: keeping previous videos", file=sys.stderr)
            vids = previous.get(ch["key"], vids)
        for v in vids:
            v.setdefault("thumb", thumb_url(v["id"]))
        result[ch["key"]] = vids
        print(f"  {ch['name']}: " + " | ".join(v["title"] for v in vids))
    return result


# ── Rendering ───────────────────────────────────────────────────────────────

e = html.escape


def video_panel(v, size):
    return f'''<a class="panel vid {size} reveal" href="https://www.youtube.com/watch?v={e(v["id"])}">
  <img src="{e(v["thumb"])}" alt="{e(v["title"])}" loading="lazy" width="1280" height="720">
  <span class="play" aria-hidden="true"></span>
  <span class="caption">{e(v["title"])}</span>
</a>'''


def channel_section(ch, vids, flip):
    sub = f"https://www.youtube.com/@{ch['handle']}?sub_confirmation=1"
    videos = "".join(video_panel(v, "big" if i == 0 else "small") for i, v in enumerate(vids))
    return f'''<section class="channel {ch["key"]}{" flip" if flip else ""}" id="{ch["key"]}" aria-labelledby="h-{ch["key"]}">
  <div class="wrap channel-grid">
    <div class="intro">
      <img class="logo reveal" src="assets/logo-{ch["key"]}.jpg" alt="{e(ch["name"])} logo" width="400" height="400">
      <div class="intro-text">
        <h2 id="h-{ch["key"]}" class="reveal">{e(ch["name"])}</h2>
        <p class="tagline reveal">{e(ch["tagline"])}</p>
        <p class="about reveal">{e(ch["about"])}</p>
        <a class="btn reveal" href="{sub}">Subscribe</a>
      </div>
    </div>
    <div class="videos">
      <h3 class="latest-label">Latest episodes</h3>
      <div class="vid-grid">{videos}</div>
      <a class="more" href="https://www.youtube.com/@{ch["handle"]}/videos">All {e(ch["name"])} videos</a>
    </div>
  </div>
</section>'''


def product_panel(p, i):
    name, kind, price, path, img = p
    return f'''<a class="panel product reveal" href="{STORE}{e(path)}" style="--tilt:{(-1.5, 1.2, -0.8, 1.6, 1, -1.3, 1.5, -0.7)[i % 8]}deg">
  <img src="{IMG}{e(img)}" alt="{e(name)} {e(kind.lower())}" loading="lazy" width="650" height="650">
  <span class="ph" aria-hidden="true">{e(name)}</span>
  <span class="tag">{e(price)}</span>
  <span class="pname">{e(kind)}</span>
</a>'''


# Public web config of the Firebase project behind the ideas board (safe to ship:
# access is enforced by firestore.rules, not by keeping these secret).
FIREBASE = {"apiKey": "", "authDomain": "", "projectId": "", "appId": ""}
ADMINS = ["brattorre@gmail.com"]  # must match isAdmin() in firestore.rules

TITLE = "NerdScience Official: NerdScience, NerdHistory & NerdNature"
DESC = ("NerdScience drops superheroes, historical armies and apex predators into impossible "
        "fights and uses real science to call the winner. Watch the latest episodes and shop the merch.")


def json_ld():
    channels = [f"https://www.youtube.com/@{c['handle']}" for c in CHANNELS]
    return json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "@id": SITE + "#org", "name": "NerdScience",
             "alternateName": ["NerdVerse", "NerdScience Official"], "url": SITE,
             "logo": SITE + "assets/icon-192.png", "description": DESC, "sameAs": channels + [STORE]},
            {"@type": "WebSite", "@id": SITE + "#site", "name": "NerdScience Official",
             "url": SITE, "publisher": {"@id": SITE + "#org"}},
        ],
    }, ensure_ascii=False).replace("</", "<\\/")


def write_seo_files():
    (HERE / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}sitemap.xml\n")
    (HERE / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{SITE}</loc><lastmod>{datetime.now():%Y-%m-%d}</lastmod><changefreq>daily</changefreq></url>\n"
        f"  <url><loc>{SITE}ideas/</loc><lastmod>{datetime.now():%Y-%m-%d}</lastmod><changefreq>daily</changefreq></url>\n"
        "</urlset>\n")


def render(data):
    hero_thumbs = [data[c["key"]][0] for c in CHANNELS]
    strip = "".join(
        f'<a class="panel strip-{c["key"]} reveal" href="#{c["key"]}"><img src="{e(v["thumb"])}" alt="{e(v["title"])}" width="1280" height="720">'
        f'<span class="caption">{e(c["name"])}</span></a>'
        for c, v in zip(CHANNELS, hero_thumbs))
    sections = "".join(channel_section(c, data[c["key"]], i % 2 == 1) for i, c in enumerate(CHANNELS))
    products = "".join(product_panel(p, i) for i, p in enumerate(PRODUCTS))
    built = datetime.now().strftime("%-d %B %Y")
    return (TEMPLATE.replace("%%STRIP%%", strip).replace("%%SECTIONS%%", sections)
            .replace("%%PRODUCTS%%", products).replace("%%DESIGN%%", DESIGN).replace("%%STORE%%", STORE)
            .replace("%%BUILT%%", built).replace("%%TITLE%%", e(TITLE)).replace("%%DESC%%", e(DESC))
            .replace("%%JSONLD%%", json_ld()).replace("%%SITE%%", SITE))


TEMPLATE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<meta name="description" content="%%DESC%%">
<link rel="canonical" href="%%SITE%%">
<meta property="og:type" content="website">
<meta property="og:site_name" content="NerdScience">
<meta property="og:url" content="%%SITE%%">
<meta property="og:title" content="%%TITLE%%">
<meta property="og:description" content="%%DESC%%">
<meta property="og:image" content="%%SITE%%assets/og.jpg?v=2">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="NerdScience logo between Kratos, Leon Kennedy and Batman, above the words Who survives?">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="%%TITLE%%">
<meta name="twitter:description" content="%%DESC%%">
<meta name="twitter:image" content="%%SITE%%assets/og.jpg?v=2">
<script type="application/ld+json">%%JSONLD%%</script>
<link rel="icon" href="favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="assets/icon-32.png">
<link rel="icon" type="image/png" sizes="192x192" href="assets/icon-192.png">
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">
<meta name="theme-color" content="#141414">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bangers&family=Barlow:wght@500;700;800&display=swap" rel="stylesheet">
<style>
:root{
  --ink:#141414; --paper:#fffdf5; --yellow:#ffd60a;
  --green:#1e9b4a; --red:#d62631; --blue:#1d66d6;
  --display:"Bangers","Impact","Arial Narrow Bold",sans-serif;
  --text:"Barlow","Helvetica Neue",Arial,sans-serif;
  --line:4px; --drop:7px; --m:clamp(16px,4vw,48px);
}
*{box-sizing:border-box;margin:0}
html{scroll-behavior:smooth}
body{background:var(--paper);color:var(--ink);font:500 18px/1.55 var(--text)}
img{display:block;max-width:100%;height:auto}
a{color:inherit}
.wrap{max-width:1360px;margin:0 auto;padding-inline:var(--m)}
h1,h2,h3{font-family:var(--display);font-weight:400;letter-spacing:.01em;line-height:.95}
:focus-visible{outline:4px solid var(--ink);outline-offset:3px}

/* Halftone: the dot screen of printed comics */
.dots{background-image:radial-gradient(rgba(20,20,20,.16) 1.6px,transparent 1.7px);background-size:12px 12px} /* taste-skill-ignore: comic print offset + halftone, requested style */

/* Panels: thick ink line and a hard printed offset */
.panel{position:relative;display:block;border:var(--line) solid var(--ink);background:var(--paper);
  box-shadow:var(--drop) var(--drop) 0 var(--ink);text-decoration:none;overflow:hidden; /* taste-skill-ignore: comic print offset + halftone, requested style */
  transition:transform .18s ease,box-shadow .18s ease}
.panel:hover{transform:translate(-3px,-3px) rotate(-.6deg);box-shadow:calc(var(--drop) + 4px) calc(var(--drop) + 4px) 0 var(--ink)} /* taste-skill-ignore: comic print offset + halftone, requested style */
.panel:active{transform:translate(2px,2px);box-shadow:3px 3px 0 var(--ink)} /* taste-skill-ignore: comic print offset + halftone, requested style */
.panel img{width:100%;aspect-ratio:16/9;object-fit:cover}
.caption{position:absolute;left:-4px;bottom:-4px;max-width:92%;background:var(--yellow);border:var(--line) solid var(--ink);
  padding:.35em .7em;font:800 .95rem/1.25 var(--text)}

.btn{display:inline-block;font:400 1.5rem/1 var(--display);letter-spacing:.03em;padding:.55em 1em .45em;
  background:var(--yellow);color:var(--ink);border:var(--line) solid var(--ink);box-shadow:5px 5px 0 var(--ink); /* taste-skill-ignore: comic print offset + halftone, requested style */
  text-decoration:none;transition:transform .15s ease,box-shadow .15s ease}
.btn:hover{transform:translate(-2px,-2px);box-shadow:7px 7px 0 var(--ink)} /* taste-skill-ignore: comic print offset + halftone, requested style */
.btn:active{transform:translate(3px,3px);box-shadow:2px 2px 0 var(--ink)} /* taste-skill-ignore: comic print offset + halftone, requested style */

/* Nav */
.nav{background:var(--ink);color:var(--paper)}
.nav .wrap{display:flex;align-items:center;justify-content:space-between;gap:1rem;min-height:68px;flex-wrap:wrap}
.brand{font:400 2rem/1 var(--display);color:var(--yellow);text-decoration:none;letter-spacing:.03em}
.nav ul{display:flex;gap:clamp(.8rem,2.5vw,2rem);list-style:none;padding:0;font-weight:700}
.nav ul a{text-decoration:none}
.nav ul a:hover{color:var(--yellow)}

/* Hero */
.hero{background-color:var(--yellow);border-bottom:var(--line) solid var(--ink);padding-block:clamp(48px,7vw,96px) clamp(56px,8vw,112px)}
.hero-grid{display:grid;grid-template-columns:1.05fr 1fr;gap:clamp(32px,5vw,72px);align-items:center}
.hero h1{font-size:clamp(3.4rem,6.4vw,6.8rem);text-shadow:5px 5px 0 var(--paper)} /* taste-skill-ignore: comic ink offset on display type */
.hero .lede{font-size:clamp(1.15rem,1.7vw,1.4rem);font-weight:700;max-width:30em;margin-block:28px 36px}
.bubble{position:relative;display:inline-block;background:var(--paper);border:var(--line) solid var(--ink);border-radius:50%;
  padding:.7em 1.4em;font:400 clamp(1.4rem,2.4vw,2rem)/1 var(--display);margin-bottom:22px;transform:rotate(-3deg)}
.bubble::after{content:"";position:absolute;left:28%;bottom:-22px;border:12px solid transparent;border-top:20px solid var(--ink)}
.splash{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.splash .panel:first-child{grid-column:1/-1;transform:rotate(-1.2deg)}
.splash .panel:nth-child(2){transform:rotate(1.4deg)}
.splash .panel:nth-child(3){transform:rotate(-.8deg)}
.splash .strip-science .caption{background:var(--green);color:var(--paper)}
.splash .strip-history .caption{background:var(--red);color:var(--paper)}
.splash .strip-nature .caption{background:var(--blue);color:var(--paper)}
.badges{display:flex;gap:14px;margin-top:40px}
.badges a{display:block;width:clamp(64px,7vw,92px);transition:transform .18s ease}
.badges a:hover{transform:rotate(-8deg) scale(1.08)}
.badges img{border-radius:50%;border:var(--line) solid var(--ink)}

/* What it is */
.what{padding-block:clamp(72px,10vw,140px)}
.what-grid{display:grid;grid-template-columns:1fr 1.3fr;gap:clamp(32px,6vw,96px);align-items:start}
.what h2{font-size:clamp(3rem,6vw,5.5rem)}
.beats{display:grid;gap:22px;list-style:none;padding:0}
.beats li{border:var(--line) solid var(--ink);box-shadow:var(--drop) var(--drop) 0 var(--ink);background:var(--paper);padding:20px 24px} /* taste-skill-ignore: comic print offset + halftone, requested style */
.beats li:nth-child(1){transform:rotate(-.7deg);background:var(--paper)}
.beats li:nth-child(2){transform:rotate(.6deg);margin-left:clamp(0px,4vw,48px)}
.beats li:nth-child(3){transform:rotate(-.4deg);margin-left:clamp(0px,8vw,96px)}
.beats strong{display:block;font:400 2rem/1 var(--display);margin-bottom:6px}

/* Channels */
.channel{border-top:var(--line) solid var(--ink);padding-block:clamp(72px,9vw,128px);color:var(--paper)}
.channel.science{background-color:var(--green)}
.channel.history{background-color:var(--red)}
.channel.nature{background-color:var(--blue)}
.channel-grid{display:grid;grid-template-columns:minmax(280px,.8fr) 1.4fr;gap:clamp(32px,5vw,80px);align-items:start}
.channel.flip .channel-grid{grid-template-columns:1.4fr minmax(280px,.8fr)}
.channel.flip .intro{order:2}
.logo{width:clamp(140px,16vw,220px);border-radius:50%;border:var(--line) solid var(--ink);box-shadow:var(--drop) var(--drop) 0 var(--ink);margin-bottom:28px;transform:rotate(-4deg)} /* taste-skill-ignore: comic print offset + halftone, requested style */
.channel h2{font-size:clamp(3.2rem,6vw,5.8rem);color:var(--yellow);text-shadow:4px 4px 0 var(--ink)} /* taste-skill-ignore: comic ink offset on display type */
.tagline{font:400 1.6rem/1.1 var(--display);letter-spacing:.03em;margin-block:10px 16px}
.about{max-width:32em;margin-bottom:28px}
.latest-label{font-size:2rem;color:var(--yellow);text-shadow:3px 3px 0 var(--ink);margin-bottom:18px} /* taste-skill-ignore: comic ink offset on display type */
.vid-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px}
.vid.big{grid-column:1/-1}
.vid{color:var(--ink)}
.vid.small:nth-child(2){transform:rotate(-.8deg)}
.vid.small:nth-child(3){transform:rotate(.8deg)}
.vid.big .caption{font-size:1.15rem}
.vid.small .caption{font-size:.82rem;padding:.3em .55em}
.play{position:absolute;top:14px;right:14px;width:52px;height:52px;border-radius:50%;background:var(--yellow);border:var(--line) solid var(--ink)}
.play::after{content:"";position:absolute;left:19px;top:13px;border:9px solid transparent;border-left:14px solid var(--ink);border-right:0}
.vid.small .play{width:40px;height:40px;top:10px;right:10px}
.vid.small .play::after{left:13px;top:8px;border-width:8px 0 8px 12px}
.more{display:inline-block;margin-top:26px;font-weight:800;text-underline-offset:4px}

/* Ideas call-out */
.pitch{background:var(--ink);color:var(--paper);border-top:var(--line) solid var(--ink);padding-block:clamp(64px,8vw,104px)}
.pitch-grid{display:flex;justify-content:space-between;align-items:center;gap:32px;flex-wrap:wrap}
.pitch h2{font-size:clamp(3rem,6vw,5.5rem);color:var(--yellow)}
.pitch p{max-width:34em;margin-top:14px;font-weight:700}

/* Store */
.store{background-color:var(--yellow);border-top:var(--line) solid var(--ink);padding-block:clamp(72px,9vw,128px)}
.store-head{display:flex;justify-content:space-between;align-items:end;gap:24px;flex-wrap:wrap;margin-bottom:48px}
.store h2{font-size:clamp(3.2rem,7vw,6.5rem);text-shadow:5px 5px 0 var(--paper)} /* taste-skill-ignore: comic ink offset on display type */
.store-head p{max-width:28em;font-weight:700;margin-top:12px}
.products{display:grid;grid-template-columns:repeat(4,1fr);gap:40px 26px}
.product{transform:rotate(var(--tilt));padding-bottom:16px}
.product img{aspect-ratio:1;background:#eee}
.product.noimg img{display:none}
.product .ph{display:none}
.product.noimg .ph{display:grid;place-items:center;aspect-ratio:1;background:var(--green);color:var(--yellow);font:400 2.2rem/1 var(--display);text-align:center;padding:16px;text-shadow:3px 3px 0 var(--ink)} /* taste-skill-ignore: comic ink offset on display type */
.tag{position:absolute;top:12px;left:12px;background:var(--red);color:var(--paper);border:var(--line) solid var(--ink);
  font:400 1.5rem/1 var(--display);padding:.3em .5em .2em;transform:rotate(-6deg)}
.pname{display:block;font:400 1.6rem/1 var(--display);padding:14px 16px 2px;letter-spacing:.02em}
.pkind{display:block;padding:0 16px;font-weight:700}

/* Footer */
.foot{background:var(--ink);color:var(--paper);padding-block:clamp(64px,8vw,104px) 40px}
.foot .big{font:400 clamp(4rem,15vw,14rem)/.85 var(--display);color:var(--yellow);letter-spacing:.01em}
.foot-row{display:flex;justify-content:space-between;gap:24px;flex-wrap:wrap;margin-top:40px}
.foot ul{display:flex;gap:24px;flex-wrap:wrap;list-style:none;padding:0;font-weight:700}
.foot ul a{text-decoration:none}
.foot ul a:hover{color:var(--yellow)}
.fine{max-width:46em;font-size:.95rem;margin-top:28px;color:#d9d6cc}

/* Entrances: only hidden when the script is running */
.js .reveal{opacity:0;translate:0 24px;transition:opacity .5s ease,translate .5s cubic-bezier(.2,.8,.2,1)}
.js .reveal.in{opacity:1;translate:0 0}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  .js .reveal{opacity:1;translate:none;transition:none}
  .panel,.btn,.badges a{transition:none}
}

@media (max-width:960px){
  .hero-grid,.what-grid,.channel-grid{grid-template-columns:1fr}
  .channel.flip .channel-grid{grid-template-columns:1fr}
  .channel.flip .intro{order:0}
  .intro{display:grid;grid-template-columns:auto 1fr;gap:24px;align-items:start}
  .logo{width:120px;margin:0}
  .products{grid-template-columns:repeat(2,1fr)}
}
@media (max-width:560px){
  body{font-size:17px}
  .intro{grid-template-columns:1fr}
  .vid-grid{grid-template-columns:1fr}
  .vid.small:nth-child(n){transform:none}
  .caption{font-size:.85rem}
  .beats li:nth-child(n){margin-left:0}
  .nav ul{gap:.9rem;font-size:.95rem}
}
</style>
</head>
<body>
<header class="nav">
  <div class="wrap">
    <a class="brand" href="#top">NerdVerse</a>
    <nav aria-label="Main"><ul>
      <li><a href="#science">NerdScience</a></li>
      <li><a href="#history">NerdHistory</a></li>
      <li><a href="#nature">NerdNature</a></li>
      <li><a href="ideas/">Ideas</a></li>
      <li><a href="#store">Store</a></li>
    </ul></nav>
  </div>
</header>

<main id="top">
<section class="hero dots" aria-labelledby="h-hero">
  <div class="wrap hero-grid">
    <div>
      <p class="bubble">Who survives?</p>
      <h1 id="h-hero">Welcome to<br>the NerdVerse</h1>
      <p class="lede">Three YouTube channels that drop heroes, armies and animals into impossible fights, then use real science to call the winner.</p>
      <a class="btn" href="#science">Watch the latest episodes</a>
      <div class="badges">
        <a href="#science"><img src="assets/logo-science.jpg" alt="NerdScience" width="400" height="400"></a>
        <a href="#history"><img src="assets/logo-history.jpg" alt="NerdHistory" width="400" height="400"></a>
        <a href="#nature"><img src="assets/logo-nature.jpg" alt="NerdNature" width="400" height="400"></a>
      </div>
    </div>
    <div class="splash">%%STRIP%%</div>
  </div>
</section>

<section class="what" aria-labelledby="h-what">
  <div class="wrap what-grid">
    <h2 id="h-what" class="reveal">One question, three worlds</h2>
    <ol class="beats">
      <li class="reveal"><strong>Pick a fighter</strong>A superhero, a Roman legion, a silverback gorilla. Anyone with a record we can measure.</li>
      <li class="reveal"><strong>Drop them somewhere impossible</strong>Helm's Deep, the Alamo, the Ice Age, a horror movie. The worse the odds, the better.</li>
      <li class="reveal"><strong>Let the science decide</strong>Real feats, real weapons, real anatomy. No plot armour, just the numbers.</li>
    </ol>
  </div>
</section>

%%SECTIONS%%

<section class="pitch" aria-labelledby="h-pitch">
  <div class="wrap pitch-grid">
    <div>
      <h2 id="h-pitch" class="reveal">Pick the next fight</h2>
      <p class="reveal">Suggest a matchup for any of the three channels and vote for the ones you want to see. Every day the idea that gains the most votes wins.</p>
    </div>
    <a class="btn reveal" href="ideas/">Submit and vote</a>
  </div>
</section>

<section class="store dots" id="store" aria-labelledby="h-store">
  <div class="wrap">
    <div class="store-head">
      <div>
        <h2 id="h-store" class="reveal">Wear the NerdVerse</h2>
        <p class="reveal">The Nerd Science Logo on tees, hoodies, mugs and more, printed to order.</p>
      </div>
      <a class="btn reveal" href="%%STORE%%%%DESIGN%%">Shop the logo collection</a>
    </div>
    <div class="products">%%PRODUCTS%%</div>
  </div>
</section>
</main>

<footer class="foot">
  <div class="wrap">
    <p class="big">NerdVerse</p>
    <div class="foot-row">
      <ul>
        <li><a href="https://www.youtube.com/@NerdScienceOfficial">NerdScience on YouTube</a></li>
        <li><a href="https://www.youtube.com/@NerdHistoryNs">NerdHistory on YouTube</a></li>
        <li><a href="https://www.youtube.com/@NerdNatureNs">NerdNature on YouTube</a></li>
        <li><a href="%%STORE%%">Store</a></li>
      </ul>
      <p>Videos updated %%BUILT%%</p>
    </div>
    <p class="fine">The NerdVerse channels are independent, fan-made projects, not affiliated with, authorized, endorsed or sponsored by DC Comics, Marvel, Warner Bros. Discovery, The Walt Disney Company or any other rights holder. All characters, names and related properties belong to their respective owners.</p>
  </div>
</footer>

<script>
document.documentElement.classList.add("js");
(function(){
  var els=[].slice.call(document.querySelectorAll(".reveal"));
  if(!("IntersectionObserver" in window)){els.forEach(function(el){el.classList.add("in")});return}
  var io=new IntersectionObserver(function(entries){
    entries.forEach(function(en){
      if(!en.isIntersecting)return;
      var sib=[].slice.call(en.target.parentNode.querySelectorAll(":scope > .reveal"));
      en.target.style.transitionDelay=(Math.max(0,sib.indexOf(en.target))*70)+"ms";
      en.target.classList.add("in");io.unobserve(en.target);
    });
  },{rootMargin:"0px 0px -8% 0px"});
  els.forEach(function(el){io.observe(el)});
  document.querySelectorAll(".product img").forEach(function(img){
    function off(){img.closest(".product").classList.add("noimg")}
    if(img.complete&&!img.naturalWidth)off();else img.addEventListener("error",off,{once:true});
  });
  // A failed hotlinked image falls back to the low-res YouTube thumb rather than a broken icon
  document.querySelectorAll('img[src*="maxresdefault"]').forEach(function(img){
    img.addEventListener("error",function(){img.src=img.src.replace("maxresdefault","hqdefault")},{once:true});
  });
})();
</script>
</body>
</html>
'''


def render_ideas():
    css = TEMPLATE[TEMPLATE.index("<style>") + 7:TEMPLATE.index("</style>")]
    cfg = json.dumps({"firebase": FIREBASE, "admins": ADMINS}).replace("</", "<\\/")
    return (IDEAS_TEMPLATE.replace("%%CSS%%", css).replace("%%CFG%%", cfg)
            .replace("%%SITE%%", SITE).replace("%%STORE%%", STORE))


IDEAS_TEMPLATE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pick the next fight: NerdScience ideas board</title>
<meta name="description" content="Suggest a matchup for NerdScience, NerdHistory or NerdNature and vote for the ideas you want to see. A new winner every day.">
<link rel="canonical" href="%%SITE%%ideas/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="NerdScience">
<meta property="og:url" content="%%SITE%%ideas/">
<meta property="og:title" content="Pick the next NerdScience fight">
<meta property="og:description" content="Suggest a matchup and vote for the ideas you want to see. A new winner every day.">
<meta property="og:image" content="%%SITE%%assets/og.jpg?v=2">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="../favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="../assets/icon-32.png">
<link rel="apple-touch-icon" href="../assets/apple-touch-icon.png">
<meta name="theme-color" content="#141414">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bangers&family=Barlow:wght@500;700;800&display=swap" rel="stylesheet">
<style>%%CSS%%
/* Ideas board */
.board-hero{background-color:var(--red);color:var(--paper);border-bottom:var(--line) solid var(--ink);padding-block:clamp(48px,7vw,88px)}
.board-hero h1{font-size:clamp(3.4rem,7.5vw,7.5rem);color:var(--yellow);text-shadow:5px 5px 0 var(--ink)} /* taste-skill-ignore: comic ink offset on display type */
.board-hero .lede{font-size:clamp(1.1rem,1.6vw,1.35rem);font-weight:700;max-width:36em;margin-block:20px 28px}
#auth{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.who{font-weight:700}
.linkbtn{background:none;border:0;color:inherit;font:800 1rem var(--text);text-decoration:underline;text-underline-offset:4px;cursor:pointer;padding:0}
.btn{cursor:pointer}
.btn.sm{font-size:1.15rem;padding:.45em .8em .35em;box-shadow:3px 3px 0 var(--ink)} /* taste-skill-ignore: comic print offset */
.top-grid{display:grid;grid-template-columns:1fr 1fr;gap:clamp(28px,4vw,56px);padding-block:clamp(56px,7vw,96px)}
.box{border:var(--line) solid var(--ink);box-shadow:var(--drop) var(--drop) 0 var(--ink);padding:clamp(20px,3vw,32px)} /* taste-skill-ignore: comic print offset */
.box h2{font-size:clamp(2.2rem,4vw,3.2rem);margin-bottom:16px}
.winbox{background:var(--green);color:var(--paper)}
.winbox h2{color:var(--yellow);text-shadow:3px 3px 0 var(--ink)} /* taste-skill-ignore: comic ink offset on display type */
.w-day{font-weight:800}
.w-title{font:400 clamp(2rem,3.6vw,3rem)/1 var(--display);letter-spacing:.02em;margin-block:8px 10px;color:var(--yellow)}
.w-meta,.w-none{font-weight:700}
#winners{list-style:none;padding:0;margin-top:22px;display:grid;gap:8px}
#winners li{background:rgba(0,0,0,.18);padding:8px 12px;font-weight:700}
.w-d{display:inline-block;min-width:4.5em;color:var(--yellow)}
.w-g{color:var(--yellow)}
.subbox{background:var(--paper)}
.subbox label{display:block;font-weight:800;margin:14px 0 6px}
.subbox input,.subbox textarea,.subbox select{width:100%;font:500 1rem/1.4 var(--text);padding:10px 12px;border:3px solid var(--ink);background:#fff;color:var(--ink)}
.subbox textarea{min-height:96px;resize:vertical}
.subbox .btn{margin-top:18px}
.hint{font-size:.9rem;font-weight:700;margin-top:6px}
#submit-msg,#board-status{font-weight:800;margin-top:12px}
.bad{color:var(--red)}
#mine h3{font-size:1.6rem;margin:24px 0 8px}
#mine ul{padding-left:1.1em}
.st{font-weight:800;font-size:.9rem;margin-left:6px}
.st-pending{color:var(--blue)}
.st-rejected{color:var(--red)}
.list-sec{background-color:var(--yellow);border-top:var(--line) solid var(--ink);padding-block:clamp(56px,7vw,96px)}
.list-head{display:flex;justify-content:space-between;align-items:end;gap:20px;flex-wrap:wrap;margin-bottom:28px}
.list-head h2{font-size:clamp(3rem,6vw,5rem);text-shadow:4px 4px 0 var(--paper)} /* taste-skill-ignore: comic ink offset on display type */
.sorts{display:flex;gap:10px}
.sorts button{font:400 1.3rem/1 var(--display);letter-spacing:.03em;padding:.45em .9em .35em;border:3px solid var(--ink);background:var(--paper);cursor:pointer}
.sorts button[aria-pressed="true"]{background:var(--ink);color:var(--yellow)}
#ideas{list-style:none;padding:0;display:grid;gap:18px}
.idea{display:grid;grid-template-columns:auto 1fr;gap:18px;align-items:start;background:var(--paper);border:var(--line) solid var(--ink);box-shadow:5px 5px 0 var(--ink);padding:16px 18px} /* taste-skill-ignore: comic print offset */
.idea:nth-child(odd){transform:rotate(-.3deg)}
.idea:nth-child(even){transform:rotate(.3deg)}
.vote{display:grid;justify-items:center;gap:2px;width:64px;padding:10px 0 8px;border:3px solid var(--ink);background:var(--paper);cursor:pointer;transition:transform .15s ease}
.vote:hover{transform:translateY(-2px)}
.vote:active{transform:translateY(1px)}
.vote .arrow{width:0;height:0;border:12px solid transparent;border-bottom:16px solid var(--ink);border-top:0}
.vote .count{font:400 1.7rem/1 var(--display)}
.vote.on{background:var(--ink);color:var(--yellow)}
.vote.on .arrow{border-bottom-color:var(--yellow)}
.idea h3{font:800 1.25rem/1.3 var(--text);margin:6px 0 4px}
.idea p{margin-bottom:6px}
.chtag{display:inline-block;font:400 1.05rem/1 var(--display);letter-spacing:.04em;padding:.3em .55em .2em;color:var(--paper);background:var(--ink)}
.ch-science .chtag{background:var(--green)}
.ch-history .chtag{background:var(--red)}
.ch-nature .chtag{background:var(--blue)}
.by{font-size:.92rem;font-weight:700}
.empty{font-weight:800;padding:20px 0}
.admin{background:var(--ink);color:var(--paper);padding-block:clamp(48px,6vw,80px)}
.admin h2{font-size:clamp(2.4rem,5vw,4rem);color:var(--yellow);margin-bottom:20px}
#queue{list-style:none;padding:0;display:grid;gap:14px}
#queue>li{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;background:#262626;padding:16px 18px}
#queue strong{display:block;margin:6px 0 2px;font-size:1.1rem}
.q-actions{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
@media (max-width:860px){.top-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header class="nav">
  <div class="wrap">
    <a class="brand" href="../">NerdVerse</a>
    <nav aria-label="Main"><ul>
      <li><a href="../#science">NerdScience</a></li>
      <li><a href="../#history">NerdHistory</a></li>
      <li><a href="../#nature">NerdNature</a></li>
      <li><a href="./" aria-current="page">Ideas</a></li>
      <li><a href="../#store">Store</a></li>
    </ul></nav>
  </div>
</header>

<main>
<section class="board-hero" aria-labelledby="h-board">
  <div class="wrap">
    <h1 id="h-board">Pick the next fight</h1>
    <p class="lede">Suggest a matchup for NerdScience, NerdHistory or NerdNature, then vote for the ideas you want to see. Every day at 9:30 AM ET, the idea that gained the most votes in the last 24 hours wins.</p>
    <div id="auth"><span class="who">Loading…</span></div>
    <p id="board-status" role="status"></p>
  </div>
</section>

<div class="wrap top-grid">
  <section class="box winbox" aria-labelledby="h-win">
    <h2 id="h-win">Daily winner</h2>
    <div id="winner"><p class="w-none">Loading…</p></div>
    <ul id="winners"></ul>
  </section>

  <section class="box subbox" aria-labelledby="h-sub">
    <h2 id="h-sub">Suggest a fight</h2>
    <p id="submit-locked">Sign in with Google above to suggest an idea. Every idea is checked before it goes up.</p>
    <form id="submit-form" hidden>
      <label for="f-channel">Channel</label>
      <select id="f-channel" name="channel">
        <option value="science">NerdScience: comics, movies and games</option>
        <option value="history">NerdHistory: real armies and battles</option>
        <option value="nature">NerdNature: animals and predators</option>
      </select>
      <label for="f-title">The matchup</label>
      <input id="f-title" name="title" maxlength="100" minlength="8" required placeholder="Could Deadpool survive the Battle of Stalingrad?">
      <label for="f-details">Why it would be epic (optional)</label>
      <textarea id="f-details" name="details" maxlength="500"></textarea>
      <p class="hint">Ideas show up once they're approved. One vote per person per idea.</p>
      <button class="btn" type="submit">Submit idea</button>
      <p id="submit-msg" role="status"></p>
    </form>
    <div id="mine"></div>
  </section>
</div>

<section class="list-sec dots" aria-labelledby="h-list">
  <div class="wrap">
    <div class="list-head">
      <h2 id="h-list">The ideas</h2>
      <div class="sorts" role="group" aria-label="Sort ideas">
        <button type="button" data-sort="top" aria-pressed="true">Top</button>
        <button type="button" data-sort="new" aria-pressed="false">New</button>
      </div>
    </div>
    <ol id="ideas"><li class="empty">Loading ideas…</li></ol>
  </div>
</section>

<section class="admin" id="admin" hidden aria-labelledby="h-admin">
  <div class="wrap">
    <h2 id="h-admin">Waiting for approval</h2>
    <ul id="queue"></ul>
  </div>
</section>
</main>

<footer class="foot">
  <div class="wrap">
    <p class="big">NerdVerse</p>
    <div class="foot-row">
      <ul>
        <li><a href="https://www.youtube.com/@NerdScienceOfficial">NerdScience on YouTube</a></li>
        <li><a href="https://www.youtube.com/@NerdHistoryNs">NerdHistory on YouTube</a></li>
        <li><a href="https://www.youtube.com/@NerdNatureNs">NerdNature on YouTube</a></li>
        <li><a href="%%STORE%%">Store</a></li>
      </ul>
    </div>
    <p class="fine">Ideas are suggestions from viewers and are not a promise that a video will be made. The NerdVerse channels are independent, fan-made projects, not affiliated with any rights holder.</p>
  </div>
</footer>
<script>window.NV = %%CFG%%;</script>
<script type="module" src="ideas.js"></script>
</body>
</html>
'''


def main():
    previous = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if "--offline" in sys.argv:
        data = previous
    else:
        print("Fetching latest uploads…")
        data = fetch_all(previous)
        if any(len(v) < 3 for v in data.values()):
            sys.exit("Not enough videos fetched and no previous run to fall back on; index.html left as is.")
        CACHE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    (HERE / "index.html").write_text(render(data))
    (HERE / "ideas" / "index.html").write_text(render_ideas())
    write_seo_files()
    print(f"Wrote {HERE / 'index.html'}")


if __name__ == "__main__":
    main()
