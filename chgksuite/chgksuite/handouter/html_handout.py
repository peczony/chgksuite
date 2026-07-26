import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

A4_WIDTH_MM = 210
DEFAULT_MARGIN_MM = 5
USABLE_WIDTH_MM = A4_WIDTH_MM - 2 * DEFAULT_MARGIN_MM

VALID_FRACTIONS = {"1/6": 1 / 6, "1/3": 1 / 3, "1/2": 1 / 2, "1": 1}

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }}
  html, body {{
    width: {width_mm}mm;
  }}
  body {{
    font-family: {font_family};
    font-size: 14pt;
    padding: 2mm;
  }}
</style>
</head>
<body>

<p>Edit this file</p>

</body>
</html>
"""


def _ensure_playwright_browser():
    """Install Chromium for Playwright if not already installed."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
    except Exception:
        logger.exception("Playwright Chromium is unusable, installing it...")
        subprocess.check_call(
            [sys.executable, "-m", "playwright", "install", "chromium"]
        )


def _fraction_to_width_mm(fraction_str):
    if fraction_str not in VALID_FRACTIONS:
        raise ValueError(
            f"Invalid fraction '{fraction_str}'. Must be one of: {', '.join(VALID_FRACTIONS)}"
        )
    return USABLE_WIDTH_MM * VALID_FRACTIONS[fraction_str]


def create_html(args):
    fraction = args.fraction
    output = args.output

    width_mm = _fraction_to_width_mm(fraction)

    if not output:
        output = f"handout_{fraction.replace('/', '_')}.html"

    if os.path.exists(output):
        print(f"Error: {output} already exists. Remove it or choose a different name.")
        sys.exit(1)

    font_family = args.font if args.font else "sans-serif"
    content = HTML_TEMPLATE.format(width_mm=f"{width_mm:.1f}", font_family=font_family)

    with open(output, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Created {output} (width: {width_mm:.1f}mm, fraction: {fraction} of A4)")


def _mm_to_px(mm):
    """Convert millimeters to CSS pixels (96 DPI)."""
    return round(mm * 96 / 25.4)


def html2img(args):
    html_path = os.path.abspath(args.filename)
    if not os.path.exists(html_path):
        print(f"Error: {html_path} not found")
        sys.exit(1)

    scale = args.scale

    base = os.path.splitext(html_path)[0]
    pdf_path = base + ".pdf"
    png_path = base + ".png"

    _ensure_playwright_browser()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # Parse the width from the HTML's CSS (look for width: XXmm on body)
        width_mm = _parse_width_from_html(html_path)
        width_px = _mm_to_px(width_mm)

        # First pass: set viewport to the correct width, measure content
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_viewport_size({"width": width_px, "height": 1})
        page.goto(f"file://{html_path}")

        height_px, content_width_px = page.evaluate(
            """() => {
            const body = document.body;
            const html = document.documentElement;
            return [
                Math.max(body.scrollHeight, html.scrollHeight),
                Math.max(body.scrollWidth, html.scrollWidth),
            ];
        }"""
        )

        page.set_viewport_size({"width": width_px, "height": height_px})

        # PDF: use full content width (including overflow) as page width
        # so Chromium's print engine doesn't shrink-to-fit the content.
        content_width_mm = content_width_px * 25.4 / 96
        height_mm = height_px * 25.4 / 96
        page.pdf(
            path=pdf_path,
            width=f"{content_width_mm:.2f}mm",
            height=f"{height_mm:.2f}mm",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
        )
        browser.close()

        # PNG: render with device_scale_factor for high-DPI
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(device_scale_factor=scale)
        page = context.new_page()
        page.set_viewport_size({"width": width_px, "height": height_px})
        page.goto(f"file://{html_path}")
        page.screenshot(
            path=png_path,
            full_page=True,
            scale="device",
        )
        browser.close()

    print(f"Created {pdf_path} ({content_width_mm:.1f} x {height_mm:.1f} mm)")
    print(f"Created {png_path} (scale: {scale}x)")


def _parse_width_from_html(html_path):
    """Extract the body width in mm from the HTML file's CSS."""
    import re

    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    match = re.search(r"width:\s*([\d.]+)mm", content)
    if not match:
        raise ValueError(
            f"Could not find 'width: <N>mm' in {html_path}. "
            "The HTML must specify body width in millimeters."
        )
    return float(match.group(1))
