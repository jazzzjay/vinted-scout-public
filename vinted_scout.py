"""
Vinted Scout
============
Automated second-hand marketplace monitor for vintage Levi's jeans.

Monitors: Vinted, OLX, Allegro Lokalnie (+ optional Remixshop, Sellpy)
Filters:  price cap, keyword blacklist, AI vision analysis (Claude Haiku)
Notifies: Telegram

Active hours:
  Mon-Fri : 17:00 - 21:00 (PL time)
  Sat-Sun : 10:00 - 21:00 (PL time)
"""

import requests
import sqlite3
import time
import base64
import logging
import os
from datetime import datetime

import config
from scraper_olx import search_olx
from scraper_allegro import search_allegro_lokalnie
from scraper_sellpy import search_sellpy
from scraper_remixshop import search_remixshop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("VintedScout")

VINTED_BASE = "https://www.vinted.pl"
DB_FILE = os.environ.get("DB_PATH", "/data/seen_items.db")
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
    "Referer":         VINTED_BASE,
}

_REFERENCE_IMAGES_DATA: list[dict] = []


# ─── DATABASE ────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen "
        "(id TEXT PRIMARY KEY, title TEXT, seen_at TEXT)"
    )
    conn.commit()
    return conn

def is_seen(conn, item_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM seen WHERE id = ?", (item_id,)
    ).fetchone() is not None

def mark_seen(conn, item_id: str, title: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO seen (id, title, seen_at) VALUES (?, ?, ?)",
        (item_id, title, datetime.now().isoformat()),
    )
    conn.commit()


# ─── REFERENCE IMAGES ────────────────────────────────────────────────────────

def _load_examples() -> None:
    """
    Loads reference images from local files or URLs at startup.
    These are passed to Claude Vision before each analyzed photo
    so the model can calibrate its label recognition.
    """
    global _REFERENCE_IMAGES_DATA
    _REFERENCE_IMAGES_DATA = []

    ref_map = getattr(config, "REFERENCE_IMAGES", {})
    if not ref_map:
        log.info("No reference images configured — AI running without examples.")
        return

    label_names = {
        "512_yes": "Levi's 512 BOOTCUT — white label '512 BOOTCUT' visible — ACCEPT",
        "527_yes": "Levi's 527 — patch or label '527' visible — ACCEPT",
    }

    for key, paths in ref_map.items():
        label = label_names.get(key, key)
        for path in paths:
            try:
                if path.startswith("http://") or path.startswith("https://"):
                    r = requests.get(path, timeout=15)
                    if r.status_code != 200:
                        log.warning(f"  Ref HTTP {r.status_code}: {path[:80]}")
                        continue
                    data = r.content
                else:
                    with open(path, "rb") as f:
                        data = f.read()

                img_b64 = base64.standard_b64encode(data).decode()
                header  = base64.b64decode(img_b64[:16])
                if header[:3] == b"\xff\xd8\xff":   mt = "image/jpeg"
                elif header[:4] == b"\x89PNG":      mt = "image/png"
                else:                               mt = "image/webp"

                _REFERENCE_IMAGES_DATA.append({
                    "label":      label,
                    "verdict":    "YES",
                    "media_type": mt,
                    "data":       img_b64,
                })
                log.info(f"  Loaded ref [{key}]: {path}")
            except Exception as exc:
                log.warning(f"  Failed to load ref {path}: {exc}")

    log.info(f"Loaded {len(_REFERENCE_IMAGES_DATA)} reference images.")


# ─── VINTED ──────────────────────────────────────────────────────────────────

def make_vinted_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(VINTED_BASE, timeout=12)
        log.info("Vinted session OK")
    except Exception as exc:
        log.warning(f"Vinted warmup: {exc}")
    return session


def search_vinted(session, query: str) -> list[dict]:
    params = {
        "search_text": query,
        "per_page":    96,
        "page":        1,
        "order":       "newest_first",
    }
    if config.PRICE_MIN > 0: params["price_from"] = config.PRICE_MIN
    if config.PRICE_MAX > 0: params["price_to"]   = config.PRICE_MAX
    try:
        resp = session.get(
            f"{VINTED_BASE}/api/v2/catalog/items", params=params, timeout=15
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            for item in items:
                item.setdefault("source", "Vinted")
                item.setdefault("url", f"{VINTED_BASE}/items/{item.get('id','')}")
            return items
        log.warning(f"Vinted HTTP {resp.status_code}")
    except Exception as exc:
        log.error(f"Vinted: {exc}")
    return []


# ─── FILTERS ─────────────────────────────────────────────────────────────────

def _price_ok(item: dict) -> bool:
    if config.PRICE_MAX <= 0:
        return True
    raw = item.get("price")
    if raw is None or raw == "?":
        return True
    if isinstance(raw, dict):
        raw = raw.get("amount") or raw.get("value") or "?"
    try:
        val = float(str(raw).replace(",", ".").replace(" ", ""))
        return val <= config.PRICE_MAX
    except Exception:
        return True


def is_blacklisted(item: dict) -> bool:
    raw   = item.get("title", "").lower()
    title = (raw
             .replace("levi's", "levis")
             .replace("levi`s", "levis")
             .replace("levi s", "levis")
             .replace("levi-s", "levis")
             .replace("'", "")
             .replace("`", ""))
    return any(kw.lower() in title for kw in config.BLACKLIST_KEYWORDS)


# ─── AI IMAGE ANALYSIS ───────────────────────────────────────────────────────

def _analyze_photo(url: str, title: str) -> str:
    """
    Sends a single listing photo to Claude Haiku for vision analysis.

    Returns:
      'YES'   — 90%+ confident this is a matching model
      'WRONG' — definitely not a match (wrong model, shorts, children's, etc.)
      'SKIP'  — cannot determine from this photo, try the next one
    """
    try:
        r = requests.get(url, timeout=12)
        if r.status_code != 200:
            return "SKIP"

        img_b64 = base64.standard_b64encode(r.content).decode()
        header  = base64.b64decode(img_b64[:16])
        if header[:3] == b"\xff\xd8\xff":   media_type = "image/jpeg"
        elif header[:4] == b"\x89PNG":      media_type = "image/png"
        else:                               media_type = "image/webp"

        content: list[dict] = []

        if _REFERENCE_IMAGES_DATA:
            content.append({
                "type": "text",
                "text": (
                    "REFERENCE EXAMPLES — use these to calibrate your judgment.\n"
                    "Study carefully: what the white labels look like on accepted items."
                ),
            })
            for ref in _REFERENCE_IMAGES_DATA:
                content.append({
                    "type": "image",
                    "source": {
                        "type":       "base64",
                        "media_type": ref["media_type"],
                        "data":       ref["data"],
                    },
                })
                content.append({
                    "type": "text",
                    "text": f"REFERENCE ({ref['verdict']}): {ref['label']}",
                })
            content.append({
                "type": "text",
                "text": "─────────────────────────────\nNOW ANALYZE THIS LISTING IMAGE:",
            })

        content.append({
            "type": "image",
            "source": {
                "type":       "base64",
                "media_type": media_type,
                "data":       img_b64,
            },
        })
        content.append({
            "type": "text",
            "text": config.AI_IMAGE_PROMPT + f"\n\nListing title: {title}",
        })

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         config.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 5,
                "messages":   [{"role": "user", "content": content}],
            },
            timeout=30,
        )

        if resp.status_code == 200:
            answer = resp.json()["content"][0]["text"].strip().upper()
            if answer.startswith("YES"):   return "YES"
            if answer.startswith("WRONG"): return "WRONG"
            return "SKIP"

    except Exception as exc:
        log.error(f"  AI photo: {exc}")
    return "SKIP"


def ai_passes(item: dict) -> bool:
    """
    Iterates through listing photos one by one.

    YES   -> accept immediately, stop
    WRONG -> reject immediately, stop (no further API calls wasted)
    SKIP  -> move to next photo
    All SKIP -> reject (no confirmation found)
    """
    photos = item.get("photos", [])
    if not photos:
        return True

    title = item.get("title", "")

    for i, photo in enumerate(photos):
        url = photo.get("url") or photo.get("full_size_url") or ""
        if not url:
            continue

        result = _analyze_photo(url, title)
        log.info(f"  AI photo {i+1}/{len(photos)} [{result}] {title[:70]}")

        if result == "YES":
            return True

        if result == "WRONG":
            log.info(f"  WRONG on photo {i+1} — rejecting, skipping remaining photos")
            return False

        time.sleep(0.5)

    log.info(f"  All SKIP — no confirmation found, rejecting: {title[:70]}")
    return False


# ─── TELEGRAM ────────────────────────────────────────────────────────────────

def _tg(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"

SOURCE_EMOJI = {
    "Vinted":           "👗",
    "OLX":              "🟠",
    "Allegro Lokalnie": "🔴",
    "Sellpy":           "🟡",
    "Remixshop":        "🟣",
}

def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _format_price(raw) -> str:
    if raw is None or raw == "?":
        return "?"
    if isinstance(raw, dict):
        raw = raw.get("amount") or raw.get("value") or raw.get("price") or "?"
    try:
        val = float(str(raw).replace(",", ".").replace(" ", ""))
        return str(int(val)) if val == int(val) else f"{val:.2f}".replace(".", ",")
    except Exception:
        return str(raw)

def notify_telegram(item: dict) -> None:
    title  = _esc(item.get("title", "No title"))
    price  = _format_price(item.get("price"))
    curr   = _esc(item.get("currency", "PLN"))
    size   = _esc(item.get("size_title") or "")
    brand  = _esc(item.get("brand_title") or "")
    source = _esc(item.get("source", ""))
    url    = item.get("url", "")
    emoji  = SOURCE_EMOJI.get(item.get("source", ""), "📦")

    size_line  = f"📏 Size: {size}\n"  if size  and size  not in ("-", "—") else ""
    brand_line = f"🏷 Brand: {brand}\n" if brand and brand not in ("-", "—") else ""

    caption = (
        f"{emoji} <b>{source}</b>\n\n"
        f"<b>{title}</b>\n\n"
        f"💰 <b>{price} {curr}</b>\n"
        f"{size_line}"
        f"{brand_line}"
        f'🔗 <a href="{url}">Open listing</a>'
    )

    photos    = item.get("photos", [])
    photo_url = (photos[0].get("url") or photos[0].get("full_size_url")) if photos else None

    try:
        if photo_url:
            r = requests.post(
                _tg("sendPhoto"),
                json={"chat_id": config.TELEGRAM_CHAT_ID, "photo": photo_url,
                      "caption": caption, "parse_mode": "HTML"},
                timeout=12,
            )
        else:
            r = requests.post(
                _tg("sendMessage"),
                json={"chat_id": config.TELEGRAM_CHAT_ID, "text": caption,
                      "parse_mode": "HTML"},
                timeout=12,
            )
        if r.status_code == 200:
            log.info("  Telegram OK")
        else:
            log.warning(f"  Telegram {r.status_code}: {r.text[:100]}")
    except Exception as exc:
        log.error(f"  Telegram: {exc}")

def notify_telegram_text(msg: str) -> None:
    try:
        requests.post(
            _tg("sendMessage"),
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg},
            timeout=10,
        )
    except Exception:
        pass

def send_startup_message() -> None:
    platforms = []
    if config.USE_VINTED:           platforms.append("Vinted")
    if config.USE_OLX:              platforms.append("OLX")
    if config.USE_ALLEGRO_LOKALNIE: platforms.append("Allegro Lokalnie")
    if config.USE_SELLPY:           platforms.append("Sellpy")
    if config.USE_REMIXSHOP:        platforms.append("Remixshop")

    now      = _now_pl()
    is_wknd  = now.weekday() >= 5
    start_h  = config.WEEKEND_HOUR_START if is_wknd else config.WEEKDAY_HOUR_START
    queries  = "\n".join(f"  - {q}" for q in config.SEARCH_QUERIES)
    price_str = (f"\nPrice cap: {config.PRICE_MAX} PLN"
                 if config.PRICE_MAX else "")
    ref_str  = (f"\nReference images: {len(_REFERENCE_IMAGES_DATA)}"
                if _REFERENCE_IMAGES_DATA else "\nReference images: none")

    msg = (
        f"Vinted Scout started!\n\n"
        f"Platforms: {', '.join(platforms)}\n"
        f"Queries:\n{queries}"
        f"{price_str}"
        f"{ref_str}\n"
        f"Hours: {start_h}:00–{config.ACTIVE_HOUR_END}:00 "
        f"({'weekend' if is_wknd else 'weekday'})\n"
        f"Interval: every {config.CHECK_INTERVAL_MINUTES} min\n"
        f"{'AI vision: ON' if config.USE_AI_IMAGE_FILTER else 'AI vision: OFF'}"
    )
    try:
        requests.post(
            _tg("sendMessage"),
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg},
            timeout=10,
        )
    except Exception:
        pass


# ─── PROCESS ITEMS ───────────────────────────────────────────────────────────

def process_items(items: list[dict], conn, seed_mode: bool = False) -> int:
    """
    Processes a batch of listings:
      1. Skip if already seen (SQLite)
      2. Mark as seen
      3. In seed mode: stop here (just record, no analysis)
      4. Check price against PRICE_MAX
      5. Check title against blacklist
      6. Run AI vision analysis
      7. Send Telegram notification
    """
    new_count = 0

    for item in items:
        item_id = str(item.get("id", ""))
        title   = item.get("title", "")

        if not item_id or is_seen(conn, item_id):
            continue

        mark_seen(conn, item_id, title)
        new_count += 1

        if seed_mode:
            continue

        if not _price_ok(item):
            log.info(f"  Price > {config.PRICE_MAX} PLN: {title[:70]}")
            continue

        if is_blacklisted(item):
            log.info(f"  Blacklisted: {title[:70]}")
            continue

        if config.USE_AI_IMAGE_FILTER and not ai_passes(item):
            log.info(f"  AI rejected: {title[:70]}")
            continue

        notify_telegram(item)
        time.sleep(1.5)

    return new_count


# ─── TIME UTILS ──────────────────────────────────────────────────────────────

def _now_pl():
    from datetime import timezone, timedelta
    return datetime.now(tz=timezone(timedelta(hours=2)))

def _active_hour_start() -> int:
    now = _now_pl()
    return config.WEEKEND_HOUR_START if now.weekday() >= 5 else config.WEEKDAY_HOUR_START

def is_active_hour() -> bool:
    h = _now_pl().hour
    return _active_hour_start() <= h < config.ACTIVE_HOUR_END

def seconds_until_next_activation() -> float:
    from datetime import timedelta
    now    = _now_pl()
    target = now.replace(hour=_active_hour_start(), minute=0, second=0, microsecond=0)
    if now >= target:
        tomorrow = now + timedelta(days=1)
        t_start  = config.WEEKEND_HOUR_START if tomorrow.weekday() >= 5 else config.WEEKDAY_HOUR_START
        target   = tomorrow.replace(hour=t_start, minute=0, second=0, microsecond=0)
    return (target - now).total_seconds()

def wait_for_active_window() -> None:
    from datetime import timedelta
    secs     = seconds_until_next_activation()
    hours    = int(secs // 3600)
    mins     = int((secs % 3600) // 60)
    tomorrow = _now_pl() + timedelta(seconds=secs)
    start_h  = config.WEEKEND_HOUR_START if tomorrow.weekday() >= 5 else config.WEEKDAY_HOUR_START

    log.info(f"Outside active hours. Next run in {hours}h {mins}min (at {start_h}:00 PL).")
    notify_telegram_text(f"Bot sleeping. Next run at {start_h}:00. Good night!")
    while not is_active_hour():
        time.sleep(60)
        log.info(f"Waiting... (now {_now_pl().strftime('%H:%M')})")


# ─── SEED ────────────────────────────────────────────────────────────────────

def do_seed(conn, session) -> None:
    """
    On first boot: scrape all platforms and record current listings
    without sending any notifications. This prevents a flood of alerts
    for items that were already listed before the bot started.
    """
    log.info("Seeding — recording existing listings (no AI, no Telegram)...")
    for query in config.SEARCH_QUERIES:
        if config.USE_OLX:
            process_items(
                search_olx(query, config.PRICE_MIN, config.PRICE_MAX), conn, seed_mode=True
            )
            time.sleep(2)
        if config.USE_ALLEGRO_LOKALNIE:
            process_items(
                search_allegro_lokalnie(query, config.PRICE_MIN, config.PRICE_MAX), conn, seed_mode=True
            )
            time.sleep(2)
        if config.USE_VINTED and session:
            process_items(search_vinted(session, query), conn, seed_mode=True)
            time.sleep(2)
        if config.USE_REMIXSHOP:
            process_items(
                search_remixshop(query, config.PRICE_MIN, config.PRICE_MAX), conn, seed_mode=True
            )
            time.sleep(2)
        if config.USE_SELLPY:
            process_items(
                search_sellpy(query, config.PRICE_MIN, config.PRICE_MAX), conn, seed_mode=True
            )
            time.sleep(2)
    log.info("Seeding complete.")


# ─── MAIN LOOP ───────────────────────────────────────────────────────────────

def run():
    log.info("=" * 50)
    log.info("  VINTED SCOUT  -  start")
    log.info("=" * 50)

    _load_examples()

    conn    = init_db()
    session = make_vinted_session() if config.USE_VINTED else None

    first_boot = conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 0
    if first_boot:
        do_seed(conn, session)

    if not is_active_hour():
        wait_for_active_window()

    send_startup_message()
    cycle = 0

    while True:
        if not is_active_hour():
            log.info(f"Hour {config.ACTIVE_HOUR_END}:00 — shutting down for today.")
            wait_for_active_window()
            log.info(f"Waking up! Starting at {_active_hour_start()}:00.")
            notify_telegram_text(
                f"Bot active! Running until {config.ACTIVE_HOUR_END}:00 today."
            )
            session = make_vinted_session() if config.USE_VINTED else None

        cycle += 1
        log.info(f"-- Cycle #{cycle} --")

        for query in config.SEARCH_QUERIES:
            log.info(f"Searching: '{query}'")

            if config.USE_OLX:
                items = search_olx(query, config.PRICE_MIN, config.PRICE_MAX)
                log.info(f"  OLX: {len(items)} listings, new: {process_items(items, conn)}")
                time.sleep(2)

            if config.USE_ALLEGRO_LOKALNIE:
                items = search_allegro_lokalnie(query, config.PRICE_MIN, config.PRICE_MAX)
                log.info(f"  Allegro Lokalnie: {len(items)} listings, new: {process_items(items, conn)}")
                time.sleep(2)

            if config.USE_VINTED and session:
                items = search_vinted(session, query)
                log.info(f"  Vinted: {len(items)} listings, new: {process_items(items, conn)}")
                time.sleep(2)

            if config.USE_REMIXSHOP:
                items = search_remixshop(query, config.PRICE_MIN, config.PRICE_MAX)
                log.info(f"  Remixshop: {len(items)} listings, new: {process_items(items, conn)}")
                time.sleep(2)

            if config.USE_SELLPY:
                items = search_sellpy(query, config.PRICE_MIN, config.PRICE_MAX)
                log.info(f"  Sellpy: {len(items)} listings, new: {process_items(items, conn)}")
                time.sleep(2)

        if session and cycle % 10 == 0:
            session = make_vinted_session()

        log.info(f"Sleeping {config.CHECK_INTERVAL_MINUTES} min...")
        time.sleep(config.CHECK_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    run()
