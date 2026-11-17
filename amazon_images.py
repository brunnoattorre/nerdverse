#!/usr/bin/env python3
"""Fetch product photos for the episode pages' Amazon picks from Amazon's Creators API.

Amazon only lets an Associates site show product images that come from its API, and only
for 24 hours, so the daily job runs this before rendering. Results go to
episodes/product_images.json ({asin: {"url", "fetched"}}); render_episodes.py uses an image
only if it was fetched in the last 24 hours, and shows the printed product-type label otherwise.

Until the Associates account has its 3 qualifying sales, Amazon answers AssociateNotEligible;
this script then says so and changes nothing. It switches on by itself once Amazon allows it.

    AMAZON_CREDENTIAL_ID=... AMAZON_CREDENTIAL_SECRET=... python3 amazon_images.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import build  # SSL context

HERE = Path(__file__).parent
DATA = HERE / "episodes"
OUT = DATA / "product_images.json"
TOKEN_URL = "https://api.amazon.com/auth/o2/token"  # credential version 3.1 (North America)
ITEMS_URL = "https://creatorsapi.amazon/catalog/v1/getItems"
TAG = "nerdscience-20"


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30, context=build.SSL) as r:
        return json.loads(r.read())


def _image(item):
    """The largest primary image URL in an item, whatever the response's key casing."""
    def get(d, *names):
        for n in names:
            if isinstance(d, dict) and n in d:
                return d[n]
        return None
    primary = get(get(item, "images", "Images") or {}, "primary", "Primary") or {}
    for size in ("large", "Large", "medium", "Medium", "small", "Small"):
        img = get(primary, size)
        if img and get(img, "url", "URL"):
            return get(img, "url", "URL")
    return None


def main():
    cid, secret = os.environ.get("AMAZON_CREDENTIAL_ID"), os.environ.get("AMAZON_CREDENTIAL_SECRET")
    if not (cid and secret):
        print("AMAZON_CREDENTIAL_ID / AMAZON_CREDENTIAL_SECRET not set; product images skipped")
        return 0
    asins = sorted({p["asin"] for f in DATA.glob("*/*.json")
                    for p in json.loads(f.read_text()).get("products", [])})
    if not asins:
        return 0
    token = _post(TOKEN_URL, {"grant_type": "client_credentials", "client_id": cid,
                              "client_secret": secret, "scope": "creatorsapi::default"})["access_token"]
    found = {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i in range(0, len(asins), 10):  # GetItems takes up to 10 ids
        try:
            res = _post(ITEMS_URL, {"itemIds": asins[i:i + 10], "itemIdType": "ASIN",
                                    "marketplace": "www.amazon.com", "partnerTag": TAG,
                                    "resources": ["images.primary.large", "images.primary.medium"]},
                        {"Authorization": f"Bearer {token}", "x-marketplace": "www.amazon.com"})
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", "replace")
            if "AssociateNotEligible" in body:
                print("Amazon: the Associates account isn't eligible yet (it needs 3 qualifying sales). "
                      "Pages keep their printed labels; this starts working on its own once eligible.")
                return 0
            print(f"Amazon GetItems failed ({err.code}): {body[:300]}")
            return 0
        result = res.get("itemsResult") or res.get("ItemsResult") or res
        for item in result.get("items") or result.get("Items") or []:
            asin = item.get("asin") or item.get("ASIN")
            url = _image(item)
            if asin and url:
                found[asin] = {"url": url, "fetched": now}
    OUT.write_text(json.dumps(found, indent=1))
    print(f"product images: {len(found)} of {len(asins)} products")
    return 0


if __name__ == "__main__":
    sys.exit(main())
