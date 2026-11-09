"""Screenshots of the running dashboard (light, dark and phone) for the README.

    streamlit run dashboard/app.py &   # then
    python scripts/screenshots.py --url http://localhost:8501 --out screenshots

Fails if the theme switch is not fully visible without scrolling or the page shows an error.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


def ready(page: Page, url: str) -> None:
    page.goto(url, wait_until="networkidle")
    page.get_by_text("Anatomía de un ataque").wait_for(timeout=120_000)
    page.wait_for_timeout(2500)  # charts and fonts
    errors = page.locator('[data-testid="stException"]')
    if errors.count():
        raise SystemExit(f"Dashboard error: {errors.first.inner_text()}")


def theme_button(page: Page, label: str):
    return page.locator(".st-key-theme button").filter(has_text=label).first


def switch_visible(page: Page) -> None:
    box = page.locator(".st-key-theme").bounding_box()
    vw = page.viewport_size["width"]
    if not box or box["x"] < 0 or box["x"] + box["width"] > vw + 1 or box["y"] < 0:
        raise SystemExit(f"Theme switch not fully visible: {box} (viewport {vw})")
    for label in ("Auto", "Claro", "Noche"):
        theme_button(page, label).wait_for(state="visible", timeout=10_000)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8501")
    parser.add_argument("--out", type=Path, default=Path("screenshots"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        desktop = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2, color_scheme="light")
        ready(desktop, args.url)
        desktop.screenshot(path=args.out / "light-top.png")
        switch_visible(desktop)
        desktop.screenshot(path=args.out / "light-top.png")
        desktop.screenshot(path=args.out / "light.png", full_page=True)
        theme_button(desktop, "Noche").click()
        desktop.wait_for_timeout(2500)
        desktop.screenshot(path=args.out / "dark-top.png")
        desktop.screenshot(path=args.out / "dark.png", full_page=True)

        phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, color_scheme="light")
        ready(phone, args.url)
        switch_visible(phone)
        phone.screenshot(path=args.out / "phone.png")
        browser.close()
    print(f"Screenshots in {args.out}")


if __name__ == "__main__":
    main()
