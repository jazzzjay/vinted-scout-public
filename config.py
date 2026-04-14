import os

SEARCH_QUERIES = [
    "levis 512 bootcut",
    "levis 512 bootcut vintage",
    "levis 512 vintage",
    "levis 527 bootcut",
    "levis 527 bootcut vintage",
    "levis 527 vintage",
    "levis 527",
    "spodnie levis 512",
    "spodnie levis 527",
    "jeansy levis 512",
    "jeansy levis 527",
    "levis bootcut vintage",
    "levis dzwony",
    "levis flare vintage",
]

BLACKLIST_KEYWORDS = [
    "dzieci", "dziecięce", "dziecięcy", "dziecięca",
    "chłopiec", "chłopca", "chłopięce",
    "dziewczynka", "dziewczęce",
    "niemowlę", "niemowlęcy",
    "junior", "kids", "children", "baby", "toddler",
    "dla dziecka", "dla dzieci", "dziecko",
    "rozmiar 116", "rozmiar 122", "rozmiar 128", "rozmiar 134", "rozmiar 140",
    "zabawka", "zabawki", "toy", "figurka",
    "98cm", "104cm", "110cm", "116cm", "122cm",
    "128cm", "134cm", "140cm", "146cm", "152cm",
    "spodenki", "szorty", "shorts", "short",
    "krótkie", "bermuda", "bermudas", "3/4", "capri",
    "kurtka", "jacket", "bluza", "hoodie", "sweter",
    "koszula", "shirt", "sukienka", "dress",
    "marynarka", "plaszcz", "coat", "sweatshirt",
    "levis 501", "levis 502", "levis 505", "levis 506",
    "levis 507", "levis 508", "levis 510", "levis 511",
    "levis 513", "levis 514", "levis 517", "levis 519",
    "levis 520", "levis 522", "levis 541", "levis 550",
    "levis 559", "levis 560", "levis 569", "levis 570",
    "levis 580",
    "512 slim", "512 skinny", "512 straight", "512 taper", "512 regular",
    "silvertab", "silver tab", "waterless", "engineered",
]

USE_OLX              = True
USE_ALLEGRO_LOKALNIE = True
USE_VINTED           = True
USE_REMIXSHOP        = False
USE_SELLPY           = False

PRICE_MIN = 0
PRICE_MAX = 70

USE_AI_IMAGE_FILTER = True

ACTIVE_HOUR_END    = 21
WEEKDAY_HOUR_START = 17
WEEKEND_HOUR_START = 10

CHECK_INTERVAL_MINUTES = 5

REFERENCE_IMAGES = {
    "512_yes": [
        "./ref_512_1.jpeg",
        "./ref_512_2.jpeg",
    ],
    "527_yes": [
        "./ref_527.jpeg",
    ],
}

AI_IMAGE_PROMPT = """
You are a Levi's jeans authentication expert. Answer with ONE word only: YES, WRONG, or SKIP.

WHAT I AM LOOKING FOR:
- Model 512 BOOTCUT: REQUIRES a white fabric label clearly showing "512 BOOTCUT" or "512 BOOT CUT"
- Model 527: ACCEPTS either a back patch showing "527" OR a white fabric label showing "527"

CONFIDENCE RULE: Answer YES only if you are 90%+ confident. If unsure -> SKIP.

══════════════════════════════════════════════
STEP 1 — BACK PATCH (rectangular label, any color, with Levi's branding and a model number)
══════════════════════════════════════════════
The back patch is a small rectangular label sewn near the back waistband.
It can be ANY color (leather, brown, tan, black, gray, or other).
READ EACH DIGIT SEPARATELY AND CAREFULLY before deciding.

If you can read a number on the back patch:
  -> Number is 527              : model 527 confirmed -> jump to STEP 3
  -> Number is 512              : model 512 likely -> still MUST find white label -> go to STEP 2
  -> Number is anything else    : WRONG — stop immediately, do not check other photos
  -> Cannot read number clearly : go to STEP 2

══════════════════════════════════════════════
STEP 2 — WHITE FABRIC LABEL (inside waistband, sewn into the jeans)
══════════════════════════════════════════════
This is a small white rectangular fabric label, usually inside the waistband.
The reference images above show exactly what these labels look like.
For model 512 it is MANDATORY — without it you cannot confirm 512 BOOTCUT.
READ EACH DIGIT SEPARATELY AND CAREFULLY before deciding.

If you can see the white fabric label:
  -> Shows "512 BOOTCUT" or "512 BOOT CUT"                        : confirmed -> go to STEP 3
  -> Shows "527" (with or without cut name, e.g. "LOW BOOT CUT")  : confirmed -> go to STEP 3
  -> Shows "512" WITHOUT the word BOOTCUT                         : WRONG — stop immediately
  -> Shows "512" + SLIM / SKINNY / STRAIGHT / TAPER / REGULAR     : WRONG — stop immediately
  -> Shows any other number                                        : WRONG — stop immediately
  -> Label not visible in this photo                              : SKIP — check next photo

══════════════════════════════════════════════
STEP 3 — CONFIRM LEVI'S BRANDING
══════════════════════════════════════════════
  -> Red tab on back pocket, Levi's stamped buttons, or any Levi's branding visible : YES
  -> No Levi's branding visible in this photo                                       : SKIP
  -> Clearly a different brand                                                      : WRONG

══════════════════════════════════════════════
INSTANT REJECTION
══════════════════════════════════════════════
  -> Item is shorts or ends above the ankle  : WRONG
  -> Children's clothing or kids sizing      : WRONG
  -> Not jeans at all                        : WRONG

══════════════════════════════════════════════
NUMBERS THAT LOOK SIMILAR — DO NOT CONFUSE
══════════════════════════════════════════════
NOT 527:  507 (middle=0)  |  517 (starts 51)  |  570 (reversed)  |  547  |  537
NOT 512:  511 (ends 1)    |  513 (ends 3)      |  502 (middle=0)  |  532

When reading a label: spell out each digit individually before deciding.

Below 90% confidence -> SKIP
Answer only: YES, WRONG, or SKIP.
"""

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
