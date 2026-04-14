import requests
import logging
import re
import json
from urllib.parse import quote

log = logging.getLogger("VintedScout.AllegroLokalnie")

BASE_URL = "https://allegrolokalnie.pl"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Referer":         BASE_URL,
}


def search_allegro_lokalnie(query: str, price_min: int = 0, price_max: int = 0) -> list[dict]:
    encoded = quote(query)
    url     = f"{BASE_URL}/oferty/q/{encoded}"
    params: dict = {"sort": "newest"}
    if price_min > 0:
        params["price_from"] = price_min
    if price_max > 0:
        params["price_to"] = price_max

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log.warning(f"Allegro Lokalnie HTTP {resp.status_code} dla '{query}'")
            return []
        return _parse(resp.text, query)
    except Exception as exc:
        log.error(f"Allegro Lokalnie blad: {exc}")
        return []


def _parse(html: str, query: str) -> list[dict]:
    items = []

    try:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if m:
            data  = json.loads(m.group(1))
            items = _find_offers(data)
            if items:
                return [n for i in items if (n := _normalize(i))]
    except Exception as exc:
        log.debug(f"Allegro __NEXT_DATA__ parse: {exc}")

    try:
        card_ids = re.findall(r'"id"\s*:\s*"?(\d+)"?', html)
        titles   = re.findall(r'"title"\s*:\s*"([^"]{5,100})"', html)
        prices   = re.findall(r'"price"\s*:\s*\{[^}]*"amount"\s*:\s*"?([\d.]+)"?', html)
        urls_raw = re.findall(r'href="(/i/[^"]+)"', html)

        seen = set()
        for i, (cid, title) in enumerate(zip(card_ids, titles)):
            if cid in seen:
                continue
            seen.add(cid)
            price = prices[i] if i < len(prices) else "?"
            slug  = urls_raw[i] if i < len(urls_raw) else f"/i/{cid}"
            items.append({
                "id":          f"al_{cid}",
                "title":       title,
                "price":       price,
                "currency":    "PLN",
                "url":         f"{BASE_URL}{slug}",
                "photos":      [],
                "size_title":  "-",
                "brand_title": "Levi's",
                "status":      "-",
                "source":      "Allegro Lokalnie",
            })
    except Exception as exc:
        log.error(f"Allegro Lokalnie HTML parse: {exc}")

    return items


def _find_offers(obj, depth: int = 0) -> list:
    if depth > 8:
        return []
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        if "id" in obj[0] and ("title" in obj[0] or "name" in obj[0]):
            return obj
        for el in obj:
            r = _find_offers(el, depth + 1)
            if r:
                return r
    if isinstance(obj, dict):
        for key in ["items", "offers", "ads", "results", "listings",
                    "pageProps", "initialData", "data", "props"]:
            if key in obj:
                r = _find_offers(obj[key], depth + 1)
                if r:
                    return r
    return []


def _normalize(item: dict) -> dict | None:
    try:
        item_id = str(item.get("id") or "")
        title   = item.get("title") or item.get("name") or ""
        if not item_id or not title:
            return None

        price_raw = item.get("price") or {}
        if isinstance(price_raw, dict):
            price = price_raw.get("amount") or price_raw.get("value") or "?"
        else:
            price = price_raw or "?"

        slug     = item.get("url") or item.get("slug") or item_id
        item_url = slug if slug.startswith("http") else f"{BASE_URL}/i/{slug}"

        photos = []
        for img in (item.get("images") or item.get("photos") or []):
            u = (img.get("url") or img.get("src") or "") if isinstance(img, dict) else str(img)
            if u:
                photos.append({"url": u})

        return {
            "id":          f"al_{item_id}",
            "title":       title,
            "price":       price,
            "currency":    "PLN",
            "url":         item_url,
            "photos":      photos,
            "size_title":  "-",
            "brand_title": "Levi's",
            "status":      "-",
            "source":      "Allegro Lokalnie",
        }
    except Exception:
        return None
