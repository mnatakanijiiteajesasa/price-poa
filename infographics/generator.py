"""
Image generation utilities for PricePoa infographics.
"""
from io import BytesIO
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# Image constants
IMG_WIDTH = 800
IMG_HEIGHT = 1200
BACKGROUND_COLOR = (255, 255, 255)  # White
PRIMARY_COLOR = (0, 102, 204)       # Blue
SECONDARY_COLOR = (102, 102, 102)   # Gray
TEXT_COLOR = (0, 0, 0)              # Black
ACCENT_COLOR = (255, 102, 0)        # Orange
GREEN_COLOR = (0, 150, 0)           # Green for cheapest
RED_COLOR = (200, 0, 0)             # Red for expensive/offer
FONT_SIZE_TITLE = 36
FONT_SIZE_HEADER = 28
FONT_SIZE_BODY = 22
FONT_SIZE_FOOTER = 18
FONT_SIZE_SMALL = 16
PADDING = 20
LINE_HEIGHT = 4
BAR_HEIGHT = 30
BAR_GAP = 10


def get_font(size):
    """Load a truetype font, fall back to default."""
    try:
        # Adjust the path if a specific font file is available
        return ImageFont.truetype("arial.ttf", size)
    except IOError:
        return ImageFont.load_default()


def draw_bar_chart(draw, x_start, y_start, bar_width, max_value, bars, labels, highlight_index=None):
    """
    Draw horizontal bar chart.
    bars: list of values (numeric)
    labels: list of labels for each bar
    highlight_index: index of bar to highlight (cheapest)
    Returns the y position after drawing the chart.
    """
    if not bars:
        return y_start
    max_bar_value = max(bars) if max(bars) > 0 else 1
    for i, (value, label) in enumerate(zip(bars, labels)):
        # Calculate bar length
        bar_length = int((value / max_bar_value) * bar_width) if max_bar_value > 0 else 0
        # Determine bar color
        if highlight_index is not None and i == highlight_index:
            bar_color = GREEN_COLOR
        else:
            bar_color = PRIMARY_COLOR
        # Draw bar
        draw.rectangle([x_start, y_start + i * (BAR_HEIGHT + BAR_GAP),
                        x_start + bar_length, y_start + i * (BAR_HEIGHT + BAR_GAP) + BAR_HEIGHT],
                       fill=bar_color)
        # Draw label
        draw.text((x_start, y_start + i * (BAR_HEIGHT + BAR_GAP) - FONT_SIZE_SMALL),
                  label, fill=TEXT_COLOR, font=get_font(FONT_SIZE_SMALL))
        # Draw value text at the end of the bar
        value_text = f"{value}"
        draw.text((x_start + bar_length + 5, y_start + i * (BAR_HEIGHT + BAR_GAP)),
                  value_text, fill=TEXT_COLOR, font=get_font(FONT_SIZE_SMALL))
    return y_start + len(bars) * (BAR_HEIGHT + BAR_GAP)


def generate_single_product_image(data: dict) -> bytes:
    """
    Generate an image for a single product.
    Expects data dict with keys: product_name, stores (list of dict with name, price, offer), date.
    Returns PNG image bytes.
    """
    img = Image.new('RGB', (IMG_WIDTH, IMG_HEIGHT), color=BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    y_current = PADDING

    # PricePoa Branding (top left)
    draw.rectangle([PADDING, PADDING, PADDING + 100, PADDING + 40], fill=PRIMARY_COLOR)
    draw.text((PADDING + 10, PADDING + 10), "PricePoa", fill=(255, 255, 255), font=get_font(FONT_SIZE_HEADER))

    # Product Name
    product_name = data.get("product_name", "Unknown Product")
    draw.text((PADDING + 120, PADDING + 15), product_name, fill=TEXT_COLOR, font=get_font(FONT_SIZE_TITLE))
    y_current = PADDING + 60

    # Date
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    draw.text((PADDING, y_current), f"Prices verified: {date_str}", fill=SECONDARY_COLOR,
              font=get_font(FONT_SIZE_SMALL))
    y_current += FONT_SIZE_SMALL + PADDING // 2

    # Horizontal price bars per store
    stores = data.get("stores", [])
    if stores:
        # Extract store names and prices (convert price string to float)
        store_names = []
        prices = []
        offer_flags = []
        for store in stores:
            store_names.append(store.get("name", "Unknown"))
            # Extract numeric price from string like "120 KES"
            price_str = store.get("price", "0")
            try:
                price_val = float(''.join(c for c in price_str if c.isdigit() or c == '.'))
            except ValueError:
                price_val = 0
            prices.append(price_val)
            offer_flags.append(store.get("offer", False))

        # Determine cheapest store (lowest price)
        if prices:
            min_price = min(prices)
            cheapest_index = prices.index(min_price)
        else:
            cheapest_index = None

        # Draw section header
        draw.text((PADDING, y_current), "Price Comparison:", fill=TEXT_COLOR,
                  font=get_font(FONT_SIZE_HEADER))
        y_current += FONT_SIZE_HEADER + PADDING // 4

        # Draw bar chart (max width for bars: IMG_WIDTH - 2*PADDING - 200 (for labels and values))
        bar_width = IMG_WIDTH - 2 * PADDING - 200
        y_current = draw_bar_chart(draw, PADDING + 150, y_current, bar_width,
                                   max(prices) if prices else 1, prices, store_names, highlight_index=cheapest_index)

        # Draw offer flags
        y_current += PADDING // 2
        for i, store in enumerate(stores):
            if store.get("offer", False):
                draw.text((PADDING, y_current + i * (BAR_HEIGHT + BAR_GAP)),
                          f"🔥 {store['name']}: Special Offer!", fill=RED_COLOR,
                          font=get_font(FONT_SIZE_SMALL))

    # Footer
    y_current = IMG_HEIGHT - PADDING - FONT_SIZE_FOOTER - 20
    draw.line([(PADDING, y_current), (IMG_WIDTH - PADDING, y_current)], fill=SECONDARY_COLOR, width=1)
    draw.text((PADDING, y_current + 10), "Scan for more prices", fill=SECONDARY_COLOR,
              font=get_font(FONT_SIZE_FOOTER))

    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()


def generate_shopping_list_image(data: dict) -> bytes:
    """
    Generate an image for a shopping list.
    Expects data dict with keys: stores (list of dict with name, total, items), recommendation, savings, date.
    Returns PNG image bytes.
    """
    img = Image.new('RGB', (IMG_WIDTH, IMG_HEIGHT), color=BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    y_current = PADDING

    # PricePoa Branding (top left)
    draw.rectangle([PADDING, PADDING, PADDING + 100, PADDING + 40], fill=PRIMARY_COLOR)
    draw.text((PADDING + 10, PADDING + 10), "PricePoa", fill=(255, 255, 255), font=get_font(FONT_SIZE_HEADER))

    # Title
    title = "Shopping List Comparison"
    draw.text((PADDING + 120, PADDING + 15), title, fill=TEXT_COLOR, font=get_font(FONT_SIZE_TITLE))
    y_current = PADDING + 60

    # Date
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    draw.text((PADDING, y_current), f"Prices verified: {date_str}", fill=SECONDARY_COLOR,
              font=get_font(FONT_SIZE_SMALL))
    y_current += FONT_SIZE_SMALL + PADDING // 2

    # Store totals as comparison bars
    stores = data.get("stores", [])
    if stores:
        store_names = []
        totals = []
        for store in stores:
            store_names.append(store.get("name", "Unknown"))
            total_str = store.get("total", "0")
            try:
                total_val = float(''.join(c for c in total_str if c.isdigit() or c == '.'))
            except ValueError:
                total_val = 0
            totals.append(total_val)

        # Determine cheapest store (lowest total)
        if totals:
            min_total = min(totals)
            cheapest_index = totals.index(min_total)
        else:
            cheapest_index = None

        # Draw section header
        draw.text((PADDING, y_current), "Store Total Comparison:", fill=TEXT_COLOR,
                  font=get_font(FONT_SIZE_HEADER))
        y_current += FONT_SIZE_HEADER + PADDING // 4

        # Draw bar chart
        bar_width = IMG_WIDTH - 2 * PADDING - 200
        y_current = draw_bar_chart(draw, PADDING + 150, y_current, bar_width,
                                   max(totals) if totals else 1, totals, store_names, highlight_index=cheapest_index)

        # Draw recommendation and savings
        y_current += PADDING // 2
        recommendation = data.get("recommendation", "")
        if recommendation:
            draw.text((PADDING, y_current), f"Recommendation: {recommendation}", fill=GREEN_COLOR,
                      font=get_font(FONT_SIZE_BODY))
            y_current += FONT_SIZE_BODY + PADDING // 4

        savings = data.get("savings", "")
        if savings:
            draw.text((PADDING, y_current), f"Savings: {savings}", fill=GREEN_COLOR,
                      font=get_font(FONT_SIZE_BODY))
            y_current += FONT_SIZE_BODY + PADDING // 4

    # Footer
    y_current = IMG_HEIGHT - PADDING - FONT_SIZE_FOOTER - 20
    draw.line([(PADDING, y_current), (IMG_WIDTH - PADDING, y_current)], fill=SECONDARY_COLOR, width=1)
    draw.text((PADDING, y_current + 10), "Scan for more prices", fill=SECONDARY_COLOR,
              font=get_font(FONT_SIZE_FOOTER))

    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()