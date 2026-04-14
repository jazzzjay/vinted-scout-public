import requests
import logging

log = logging.getLogger("VintedScout.OLX")

OLX_API = "https://www.olx.pl/api/v1/offers/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json",
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Referer":         "https://www.olx.pl/",
}


def search_olx(query: str, price_min: int = 0, price_max: int = 0) -> list[dict]:
    params: dict = {
        "query":   query,
        "limit":   50,
        "sort_by": "created_at:desc",
        "filter_refiners": "spell_checker",
    }
    if price_min > 0:
        params["filter_float_price:from"] = price_min
    if price_max > 0:
        params["filter_float_price:to"]   = price_max

    try:
        resp = requests.get(OLX_API, params=params, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log.warning(f"OLX HTTP {resp.status_code} dla '{query}'")
            return []

        raw    = resp.json().get("data", [])
        active = [i for i in raw
                  if i.get("status") not in ("limited", "inactive", "disabled", "removed")]
        return [n for item in active if (n := _normalize(item))]

    except Exception as exc:
        log.error(f"OLX blad: {exc}")
        return []


def _normalize(item: dict) -> dict | None:
    try:
        item_id = str(item.get("id") or "")
        title   = item.get("title") or ""
        if not item_id or not title:
            return None

        params     = {p["key"]: p for p in item.get("params", [])}
        price_p    = params.get("price", {})
        price      = price_p.get("value", {}).get("value", "?")
        photos     = item.get("photos", [])
        photo_urls = [
            p.get("link", "").replace("{width}", "800").replace("{height}", "600")
            for p in photos
        ]

        return {
            "id":          f"olx_{item_id}",
            "title":       title,
            "price":       price,
            "currency":    "PLN",
            "url":         item.get("url", ""),
            "photos":      [{"url": u} for u in photo_urls if u],
            "size_title":  params.get("size", {}).get("value", {}).get("label", "-"),
            "brand_title": params.get("brand", {}).get("value", {}).get("label", "-"),
            "status":      "-",
            "source":      "OLX",
        }
    except Exception:
        return None
