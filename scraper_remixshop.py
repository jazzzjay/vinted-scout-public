import requests
import logging
import re
import json

log = logging.getLogger("VintedScout.Remixshop")

BASE_URL = "https://remixshop.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Referer":         f"{BASE_URL}/pl",
}


def search_remixshop(query: str, price_min: int = 0, price_max: int = 0) -> list[dict]:
    results = _try_api(query, price_min, price_max)
    if not results:
        results = _try_html(query, price_min, price_max)
    log.info(f"  Remixshop: znaleziono {len(results)} ofert dla '{query}'")
    return results


def _try_api(query: str, price_min: int, price_max: int) -> list[dict]:
    endpoints = [
        f"{BASE_URL}/api/search",
        f"{BASE_URL}/pl/api/search",
        f"{BASE_URL}/api/products/search",
    ]
    params: dict = {"q": query, "sort": "date_desc", "lang": "pl"}
    if price_min > 0: params["price_from"] = price_min
    if price_max > 0: params["price_to"]   = price_max

    for url in endpoints:
        try:
            resp = requests.get(
                url,
                params=params,
                headers={**HEADERS, "Accept": "application/json"},
                timeout=12,
            )
            if resp.status_code == 200:
                data  = resp.json()
                items = (data.get("items") or data.get("products")
                         or data.get("results") or data.get("data") or [])
                if items:
                    return [n for i in items if (n := _normalize(i))]
        except Exception:
            continue
    return []


def _try_html(query: str, price_min: int, price_max: int) -> list[dict]:
    params: dict = {"q": query, "sort": "date_desc"}
    if price_min > 0: params["price_from"] = price_min
    if price_max > 0: params["price_to"]   = price_max

    for search_url in [f"{BASE_URL}/pl/search", f"{BASE_URL}/pl/szukaj"]:
        try:
            resp = requests.get(search_url, params=params, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                items = _parse_html(resp.text)
                if items:
                    return items
        except Exception as exc:
            log.error(f"  Remixshop HTML ({search_url}): {exc}")

    return []


def _parse_html(html: str) -> list[dict]:
    items = []

    try:
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if match:
            data  = json.loads(match.group(1))
            items = _find_list(data)
            if items:
                return [n for i in items if (n := _normalize(i))]
    except Exception:
        pass

    try:
        for block in re.findall(r'<script[^>]*>(.*?)</script>', html, re.S):
            if '"products"' in block or '"items"' in block:
                try:
                    data  = json.loads(block)
                    found = _find_list(data)
                    if found:
                        return [n for i in found if (n := _normalize(i))]
                except Exception:
                    pass
    except Exception:
        pass

    try:
        card_pattern = re.compile(
            r'href="(/pl/(?:produkt|item|p)/([^"]+))"[^>]*>.*?'
            r'(?:alt="([^"]*)")?.*?'
            r'(?:(\d[\d\s,.]*)\s*(?:PLN|zł))?',
            re.S
        )
        seen_ids = set()
        for m in card_pattern.finditer(html):
            path, slug, title, price = m.group(1), m.group(2), m.group(3), m.group(4)
            if slug in seen_ids:
                continue
            seen_ids.add(slug)
            if not title:
                continue
            items.append({
                "id":          f"remix_{slug}",
                "title":       title.strip(),
                "price":       price.strip().replace(" ", "") if price else "?",
                "currency":    "PLN",
                "url":         f"{BASE_URL}{path}",
                "photos":      [],
                "size_title":  "—",
                "brand_title": "—",
                "status":      "—",
                "source":      "Remixshop",
            })
    except Exception as exc:
        log.error(f"  Remixshop fallback parse: {exc}")

    return items


def _find_list(obj, depth: int = 0) -> list:
    if depth > 8:
        return []
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        if "id" in obj[0] and ("title" in obj[0] or "name" in obj[0] or "slug" in obj[0]):
            return obj
        for el in obj:
            r = _find_list(el, depth + 1)
            if r:
                return r
    if isinstance(obj, dict):
        for key in ["items", "products", "results", "hits",
                    "pageProps", "initialData", "data", "props"]:
            if key in obj:
                r = _find_list(obj[key], depth + 1)
                if r:
                    return r
    return []


def _normalize(item: dict) -> dict | None:
    try:
        item_id = str(item.get("id") or item.get("objectID") or item.get("sku") or "")
        title   = item.get("title") or item.get("name") or item.get("displayTitle") or ""
        if not item_id or not title:
            return None

        price_raw = item.get("price") or item.get("currentPrice") or {}
        if isinstance(price_raw, dict):
            price = price_raw.get("amount") or price_raw.get("value") or "?"
        else:
            price = price_raw or "?"

        slug     = item.get("slug") or item.get("id") or item_id
        item_url = item.get("url") or f"{BASE_URL}/pl/produkt/{slug}"

        images = item.get("images") or item.get("photos") or item.get("media") or []
        if isinstance(images, str):
            images = [images]
        photos = []
        for img in images:
            u = (img.get("url") or img.get("src") or img.get("original") or "") if isinstance(img, dict) else str(img)
            if u:
                photos.append({"url": u})

        return {
            "id":          f"remix_{item_id}",
            "title":       title,
            "price":       price,
            "currency":    "PLN",
            "url":         item_url,
            "photos":      photos,
            "size_title":  item.get("size") or item.get("sizeLabel") or "—",
            "brand_title": item.get("brand") or item.get("brandName") or "—",
            "status":      item.get("condition") or "—",
            "source":      "Remixshop",
        }
    except Exception:
        return None
