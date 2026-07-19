"""
Image generation utilities for PricePoa infographics.

Poster-style layout: gradient header banner, card-based store rows with
rank badges and mini price bars, a highlighted savings callout, and a
branded footer. Canvas height is computed dynamically from content so
there's no dead space regardless of how many stores are in the result set.
"""
from io import BytesIO
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------
IMG_WIDTH = 800
PADDING = 32

# ---------------------------------------------------------------------------
# Palette — poster-y but still on-brand. Header uses a blue gradient,
# cards sit on a soft off-white canvas (not stark white) for contrast.
# ---------------------------------------------------------------------------
CANVAS_BG = (245, 247, 250)
HEADER_TOP = (7, 71, 166)      # deep blue
HEADER_BOTTOM = (18, 120, 219)  # brighter blue
ACCENT_STRIPE = (255, 153, 0)   # orange divider under header
CARD_BG = (255, 255, 255)
CARD_BORDER = (226, 230, 236)
SHADOW_COLOR = (208, 213, 222)

TEXT_DARK = (26, 32, 44)
TEXT_MUTED = (108, 117, 130)
TEXT_ON_HEADER = (255, 255, 255)
TEXT_ON_HEADER_MUTED = (210, 226, 250)

PRIMARY = (18, 120, 219)
GREEN = (22, 163, 74)
GREEN_BG = (232, 250, 239)
ORANGE = (234, 108, 0)
ORANGE_BG = (255, 240, 222)
RED = (200, 30, 30)
GOLD = (196, 138, 0)

BAR_TRACK = (231, 235, 240)

# Ranked card accent colors (1st, 2nd, 3rd, rest)
RANK_COLORS = [GREEN, PRIMARY, (124, 58, 237), TEXT_MUTED]

FONT_SIZE_BRAND = 22
FONT_SIZE_TITLE = 34
FONT_SIZE_SUBTITLE = 18
FONT_SIZE_SECTION = 24
FONT_SIZE_STORE = 21
FONT_SIZE_PRICE = 26
FONT_SIZE_BODY = 19
FONT_SIZE_SMALL = 15

FONT_PATHS = {
    "regular": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}

_font_cache = {}


def get_font(size, bold=False):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    path = FONT_PATHS["bold"] if bold else FONT_PATHS["regular"]
    try:
        font = ImageFont.truetype(path, size)
    except IOError:
        font = ImageFont.load_default()
    _font_cache[key] = font
    return font


# ---------------------------------------------------------------------------
# Small drawing helpers
# ---------------------------------------------------------------------------

def text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(draw, text, font, max_width):
    words = text.split()
    if not words:
        return [""]
    lines, current = [], words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        w, _ = text_size(draw, trial, font)
        if w <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def vertical_gradient(size, top_color, bottom_color):
    w, h = size
    base = Image.new('RGB', (1, h), color=0)
    px = base.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        px[0, y] = tuple(int(top_color[i] + (bottom_color[i] - top_color[i]) * t) for i in range(3))
    return base.resize((w, h))


def draw_shadowed_card(draw, box, radius=16, fill=CARD_BG, outline=CARD_BORDER, shadow_offset=4):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle([x0 + shadow_offset, y0 + shadow_offset, x1 + shadow_offset, y1 + shadow_offset],
                            radius=radius, fill=SHADOW_COLOR)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline, width=1)


def draw_pill(draw, xy, text, font, fg, bg, pad_x=10, pad_y=5):
    x, y = xy
    w, h = text_size(draw, text, font)
    draw.rounded_rectangle([x, y, x + w + pad_x * 2, y + h + pad_y * 2], radius=(h + pad_y * 2) // 2, fill=bg)
    draw.text((x + pad_x, y + pad_y - 1), text, fill=fg, font=font)
    return x + w + pad_x * 2  # right edge, for chaining


def parse_amount(value) -> float:
    """Pull a float out of things like '479 KES', '1,250', 479.0, etc."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value)
    cleaned = ''.join(c for c in s if c.isdigit() or c == '.')
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def draw_header(img, draw, eyebrow, title, subtitle):
    """Gradient banner with brand pill, title (wraps if needed), subtitle line.
    Returns the y-coordinate where header content ends."""
    title_font = get_font(FONT_SIZE_TITLE, bold=True)
    max_title_width = IMG_WIDTH - 2 * PADDING

    title_lines = wrap_text(draw, title, title_font, max_title_width)
    title_lines = title_lines[:2]  # cap at 2 lines to keep header sane

    header_height = 40 + 34 + len(title_lines) * (FONT_SIZE_TITLE + 8) + FONT_SIZE_SUBTITLE + 34

    gradient = vertical_gradient((IMG_WIDTH, header_height), HEADER_TOP, HEADER_BOTTOM)
    img.paste(gradient, (0, 0))

    y = 28
    brand_font = get_font(FONT_SIZE_BRAND, bold=True)
    draw_pill(draw, (PADDING, y), "PricePoa", brand_font, PRIMARY, (255, 255, 255), pad_x=14, pad_y=8)

    eyebrow_font = get_font(FONT_SIZE_SMALL, bold=True)
    ew, _ = text_size(draw, eyebrow, eyebrow_font)
    draw.text((IMG_WIDTH - PADDING - ew, y + 10), eyebrow, fill=TEXT_ON_HEADER_MUTED, font=eyebrow_font)

    y += 34 + 12
    for line in title_lines:
        draw.text((PADDING, y), line, fill=TEXT_ON_HEADER, font=title_font)
        y += FONT_SIZE_TITLE + 8

    y += 2
    draw.text((PADDING, y), subtitle, fill=TEXT_ON_HEADER_MUTED, font=get_font(FONT_SIZE_SUBTITLE))
    y += FONT_SIZE_SUBTITLE + 20

    # accent stripe under the header
    draw.rectangle([0, header_height, IMG_WIDTH, header_height + 6], fill=ACCENT_STRIPE)

    return header_height + 6


def draw_section_title(draw, y, text):
    draw.rectangle([PADDING, y + 4, PADDING + 5, y + FONT_SIZE_SECTION + 2], fill=ACCENT_STRIPE)
    draw.text((PADDING + 16, y), text, fill=TEXT_DARK, font=get_font(FONT_SIZE_SECTION, bold=True))
    return y + FONT_SIZE_SECTION + 20


def draw_ranked_row(draw, y, width, name, amount_label, amount_value, max_value, rank, is_offer=False):
    """One card: rank badge + name (+offer pill) on top, price on the right,
    a proportional mini-bar underneath. Returns y after the card."""
    card_h = 92
    x0, x1 = PADDING, PADDING + width
    accent = RANK_COLORS[min(rank, len(RANK_COLORS) - 1)]

    draw_shadowed_card(draw, (x0, y, x1, y + card_h),
                        outline=accent if rank == 0 else CARD_BORDER)
    # left accent bar
    draw.rounded_rectangle([x0, y, x0 + 6, y + card_h], radius=3, fill=accent)

    inner_x = x0 + 22
    # rank badge (circle with number, or star for #1)
    badge_r = 16
    badge_cx, badge_cy = inner_x + badge_r, y + 24
    draw.ellipse([badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r], fill=accent)
    badge_label = "\u2605" if rank == 0 else str(rank + 1)
    bf = get_font(14, bold=True)
    bw, bh = text_size(draw, badge_label, bf)
    draw.text((badge_cx - bw / 2, badge_cy - bh / 2 - 1), badge_label, fill=(255, 255, 255), font=bf)

    name_x = inner_x + badge_r * 2 + 14
    name_font = get_font(FONT_SIZE_STORE, bold=True)
    price_font_probe = get_font(FONT_SIZE_PRICE, bold=True)
    reserved_for_price = text_size(draw, amount_label, price_font_probe)[0] + 16
    max_name_width = (x1 - 22) - name_x - reserved_for_price
    display_name = name
    if text_size(draw, display_name, name_font)[0] > max_name_width:
        while display_name and text_size(draw, display_name + "\u2026", name_font)[0] > max_name_width:
            display_name = display_name[:-1]
        display_name = display_name.rstrip() + "\u2026"
    draw.text((name_x, y + 12), display_name, fill=TEXT_DARK, font=name_font)

    pill_x = name_x
    if rank == 0:
        pill_x = draw_pill(draw, (pill_x, y + 40), "BEST PRICE", get_font(12, bold=True), (255, 255, 255), GREEN, pad_x=8, pad_y=4) + 8
    if is_offer:
        draw_pill(draw, (pill_x, y + 40), "\u25b2 OFFER", get_font(12, bold=True), ORANGE, ORANGE_BG, pad_x=8, pad_y=4)

    # price, right aligned
    price_font = get_font(FONT_SIZE_PRICE, bold=True)
    pw, _ = text_size(draw, amount_label, price_font)
    draw.text((x1 - 22 - pw, y + 14), amount_label, fill=accent if rank == 0 else TEXT_DARK, font=price_font)

    # mini proportional bar
    bar_x0 = name_x
    bar_x1 = x1 - 22
    bar_y = y + card_h - 22
    bar_w = bar_x1 - bar_x0
    draw.rounded_rectangle([bar_x0, bar_y, bar_x1, bar_y + 8], radius=4, fill=BAR_TRACK)
    frac = (amount_value / max_value) if max_value > 0 else 0
    fill_w = max(int(bar_w * frac), 6)
    draw.rounded_rectangle([bar_x0, bar_y, bar_x0 + fill_w, bar_y + 8], radius=4, fill=accent)

    return y + card_h + 14


def draw_callout(draw, y, width, headline, subline, color=GREEN, bg=GREEN_BG):
    box_h = 78
    x0, x1 = PADDING, PADDING + width
    draw.rounded_rectangle([x0, y, x1, y + box_h], radius=14, fill=bg, outline=color, width=2)
    draw.text((x0 + 20, y + 14), headline, fill=color, font=get_font(FONT_SIZE_BODY, bold=True))
    draw.text((x0 + 20, y + 14 + FONT_SIZE_BODY + 6), subline, fill=TEXT_DARK, font=get_font(FONT_SIZE_SMALL))
    return y + box_h + 20


def draw_footer(img, draw, y_top, canvas_height, note):
    draw.rectangle([0, y_top, IMG_WIDTH, canvas_height], fill=HEADER_TOP)
    text = f"\u2713 {note}"
    font = get_font(FONT_SIZE_SMALL, bold=True)
    w, h = text_size(draw, text, font)
    draw.text(((IMG_WIDTH - w) / 2, y_top + (canvas_height - y_top - h) / 2 - 4), text, fill=(255, 255, 255), font=font)
    tagline_font = get_font(12)
    tagline = "PricePoa \u2022 Compare grocery prices instantly"
    tw, th = text_size(draw, tagline, tagline_font)
    draw.text(((IMG_WIDTH - tw) / 2, canvas_height - th - 10), tagline, fill=TEXT_ON_HEADER_MUTED, font=tagline_font)


# ---------------------------------------------------------------------------
# Public generators
# ---------------------------------------------------------------------------

def generate_single_product_image(data: dict) -> bytes:
    """
    data keys: product_name, stores (list of {name, price, offer}), date, location (optional)
    """
    product_name = data.get("product_name", "Unknown Product")
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    location = data.get("location")
    subtitle = f"Verified {date_str}" + (f"  \u2022  {location}" if location else "")

    stores = data.get("stores", [])
    parsed = []
    for s in stores:
        parsed.append({
            "name": s.get("name", "Unknown"),
            "value": parse_amount(s.get("price", 0)),
            "offer": bool(s.get("offer", False)),
        })
    parsed.sort(key=lambda s: s["value"])
    max_value = max((s["value"] for s in parsed), default=1) or 1

    content_width = IMG_WIDTH - 2 * PADDING
    rows_height = len(parsed) * (92 + 14) if parsed else 40
    callout_height = 98 if len(parsed) >= 2 else 0
    header_height_estimate = 150
    footer_height = 64
    canvas_height = header_height_estimate + 30 + rows_height + callout_height + footer_height + PADDING

    img = Image.new('RGB', (IMG_WIDTH, canvas_height), color=CANVAS_BG)
    draw = ImageDraw.Draw(img)

    y = draw_header(img, draw, "SINGLE PRODUCT", product_name, subtitle)
    y += 22

    if parsed:
        y = draw_section_title(draw, y, "Price Comparison")
        for rank, s in enumerate(parsed):
            y = draw_ranked_row(draw, y, content_width, s["name"], f"KES {s['value']:,.0f}",
                                 s["value"], max_value, rank, is_offer=s["offer"])

        if len(parsed) >= 2:
            cheapest, priciest = parsed[0], parsed[-1]
            savings = priciest["value"] - cheapest["value"]
            if savings > 0:
                y = draw_callout(
                    draw, y, content_width,
                    f"Save KES {savings:,.0f} at {cheapest['name']}",
                    f"vs KES {priciest['value']:,.0f} at {priciest['name']}"
                )
    else:
        draw.text((PADDING, y), "No price data available yet.", fill=TEXT_MUTED, font=get_font(FONT_SIZE_BODY))
        y += FONT_SIZE_BODY + 20

    footer_top = canvas_height - footer_height
    draw_footer(img, draw, footer_top, canvas_height, "Prices verified by PricePoa")

    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()


def generate_shopping_list_image(data: dict) -> bytes:
    """
    data keys: stores (list of {name, total, items}), recommendation, savings, date
    """
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    item_count = data.get("item_count")
    subtitle = f"Verified {date_str}" + (f"  \u2022  {item_count} items" if item_count else "")

    stores = data.get("stores", [])
    parsed = []
    for s in stores:
        parsed.append({"name": s.get("name", "Unknown"), "value": parse_amount(s.get("total", 0))})
    parsed.sort(key=lambda s: s["value"])
    max_value = max((s["value"] for s in parsed), default=1) or 1

    content_width = IMG_WIDTH - 2 * PADDING
    rows_height = len(parsed) * (92 + 14) if parsed else 40
    recommendation = data.get("recommendation", "")
    savings = data.get("savings", "")
    callout_height = 98 if (recommendation or savings) else 0
    header_height_estimate = 150
    footer_height = 64
    canvas_height = header_height_estimate + 30 + rows_height + callout_height + footer_height + PADDING

    img = Image.new('RGB', (IMG_WIDTH, canvas_height), color=CANVAS_BG)
    draw = ImageDraw.Draw(img)

    y = draw_header(img, draw, "SHOPPING LIST", "Basket Comparison", subtitle)
    y += 22

    if parsed:
        y = draw_section_title(draw, y, "Store Totals")
        for rank, s in enumerate(parsed):
            y = draw_ranked_row(draw, y, content_width, s["name"], f"KES {s['value']:,.0f}",
                                 s["value"], max_value, rank)

        if recommendation or savings:
            headline = recommendation or "Best combination found"
            subline = f"Total savings: {savings}" if savings else ""
            y = draw_callout(draw, y, content_width, headline, subline)
    else:
        draw.text((PADDING, y), "No basket data available yet.", fill=TEXT_MUTED, font=get_font(FONT_SIZE_BODY))
        y += FONT_SIZE_BODY + 20

    footer_top = canvas_height - footer_height
    draw_footer(img, draw, footer_top, canvas_height, "Prices verified by PricePoa")

    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()