# Vinted Scout

Automated second-hand marketplace monitor for vintage Levi's jeans, built in Python and deployed on Railway.

## What it does

Continuously scrapes multiple Polish and European second-hand platforms, filters listings using keyword blacklists and price caps, then uses Claude AI vision to authenticate jeans from listing photos. Sends a Telegram notification only when a confirmed match is found.

**Platforms monitored:** Vinted · OLX · Allegro Lokalnie · Remixshop · Sellpy

**Models searched:** Levi's 512 Bootcut · Levi's 527

## How it works

```
Scrape listings
    │
    ├── Already seen? → skip (SQLite, persists across restarts)
    │
    ├── Price > 70 PLN? → skip
    │
    ├── Blacklisted keyword in title? → skip
    │
    └── AI vision analysis (Claude Haiku)
            │
            ├── Photo 1: YES → send Telegram notification
            ├── Photo 1: WRONG → reject, skip remaining photos
            └── Photo 1: SKIP → check next photo
```

## AI vision logic

Each photo is sent to Claude Haiku with reference images of known-good labels. The model follows a structured decision tree:

1. **Back patch** — reads model number; any number other than 512/527 → immediate reject
2. **White fabric label** — mandatory for 512 (must say "BOOTCUT"); sufficient for 527
3. **Levi's branding** — confirms authenticity

Confidence threshold: 90%. Below that, the model returns `SKIP` and the next photo is checked.

## Schedule

| Days | Active hours (PL time) |
|------|----------------------|
| Mon–Fri | 17:00 – 21:00 |
| Sat–Sun | 10:00 – 21:00 |

Outside these hours the bot sleeps (process stays alive on Railway, no scraping).

## Stack

- **Python 3.13** — core logic
- **requests** — HTTP scraping (no Selenium)
- **SQLite** — persistent deduplication store
- **Claude Haiku** (Anthropic API) — vision analysis
- **Telegram Bot API** — notifications
- **Railway** — cloud deployment (always-on worker)
- **GitHub** — CI/CD (auto-deploy on push)

## Project structure

```
├── vinted_scout.py       # main loop, AI analysis, Telegram
├── config.py             # search queries, filters, prompts
├── scraper_olx.py        # OLX public API
├── scraper_allegro.py    # Allegro Lokalnie (HTML scraping)
├── scraper_remixshop.py  # Remixshop (HTML scraping)
├── scraper_sellpy.py     # Sellpy (HTML scraping)
├── requirements.txt
├── Procfile              # Railway worker definition
└── refs/                 # reference images for AI calibration
    ├── ref_512_1.jpeg
    ├── ref_512_2.jpeg
    └── ref_527.jpeg
```

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/vinted-scout
cd vinted-scout
pip install -r requirements.txt
```

### 2. Set environment variables

```bash
export ANTHROPIC_API_KEY=your_key
export TELEGRAM_BOT_TOKEN=your_token
export TELEGRAM_CHAT_ID=your_chat_id
export DB_PATH=/data/seen_items.db   # or any local path
```

### 3. Run

```bash
python vinted_scout.py
```

### Deploy to Railway

1. Push repo to GitHub
2. Create a new Railway project → deploy from GitHub
3. Add environment variables in Railway → Variables
4. Add a Volume with mount path `/data` for persistent SQLite storage

## Configuration

All settings are in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `PRICE_MAX` | 70 | Maximum price in PLN |
| `USE_AI_IMAGE_FILTER` | True | Enable/disable vision analysis |
| `CHECK_INTERVAL_MINUTES` | 5 | How often to scrape |
| `WEEKDAY_HOUR_START` | 17 | Active from (Mon–Fri) |
| `WEEKEND_HOUR_START` | 10 | Active from (Sat–Sun) |
| `ACTIVE_HOUR_END` | 21 | Active until (all days) |
| `REFERENCE_IMAGES` | — | Paths to label reference photos |
