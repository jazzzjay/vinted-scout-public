import requests
import logging
import re
import json

log = logging.getLogger("VintedScout.Sellpy")

BASE_URL = "https://www.sellpy.pl"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
    "Referer":         BASE_URL,
}


def search_sellpy(query: str, price_min: int = 0, price_max: int = 0) -> list[dict]:
    results = _try_api(query, price_min, price_max)
    if not results:
        results = _try_html(query, price_min, price_max)
    log.info(f"  Sellpy: znaleziono {len(results)} ofert dla '{query}'")
    return results


def _try_api(query: str, price_min: int, price_max: int) -> list[dict]:
    params: dict = {"search": query, "sort": "new"}
    if price_min > 0:
        params["priceMin"] = price_min
    if price_max > 0:
        params["priceMax"] = price_max

    try:
        resp = requests.get(
            f"{BASE_URL}/api/search",
            params=params,
            headers={**HEADERS, "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            data  = resp.json()
            items = data.get("items") or data.get("results") or data.get("products") or []
            if items:
                return [_normalize(i) for i in items if i]
    except Exception:
        pass
    return []


def _try_html(query: str, price_min: int, price_max: int) -> list[dict]:
    params: dict = {"search": query, "sort": "new"}
    if price_min > 0: params["priceMin"] = price_min
    if price_max > 0: params["priceMax"] = price_max

    try:
        resp = requests.get(f"{BASE_URL}/pl/search", params=params, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log.warning(f"  Sellpy HTTP {resp.status_code}")
            return []
        return _parse_next_data(resp.text)
    except Exception as exc:
        log.error(f"  Sellpy HTML: {exc}")
        return []


def _parse_next_data(html: str) -> list[dict]:
    try:
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not match:
            return []
        data  = json.loads(match.group(1))
        items = _find_list(data)
        return [n for i in items if (n := _normalize(i))]
    except Exception as exc:
        log.error(f"  Sellpy parse: {exc}")
        return []


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
        item_id = str(item.get("id") or item.get("objectID") or "")
        title   = item.get("title") or item.get("name") or item.get("displayTitle") or ""
        if not item_id or not title:
            return None

        price_raw = item.get("price") or item.get("currentPrice") or {}
        if isinstance(price_raw, dict):
            price = price_raw.get("amount") or price_raw.get("value") or "?"
        else:
            price = price_raw or "?"

        slug     = item.get("slug") or item.get("id") or ""
        item_url = f"{BASE_URL}/pl/item/{slug}"

        images = item.get("images") or item.get("photos") or item.get("media") or []
        if isinstance(images, str):
            images = [images]
        photos = []
        for img in images:
            u = (img.get("url") or img.get("src") or img.get("original") or "") if isinstance(img, dict) else str(img)
            if u:
                photos.append({"url": u})

        return {
            "id":          f"sellpy_{item_id}",
            "title":       title,
            "price":       price,
            "currency":    "PLN",
            "url":         item_url,
            "photos":      photos,
            "size_title":  item.get("size") or item.get("sizeLabel") or "—",
            "brand_title": item.get("brand") or item.get("brandName") or "—",
            "status":      item.get("condition") or "—",
            "source":      "Sellpy",
        }
    except Exception:
        return None
