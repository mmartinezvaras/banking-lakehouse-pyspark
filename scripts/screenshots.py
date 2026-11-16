"""Screenshots of the running dashboard (light, dark and phone) for the README.

    streamlit run dashboard/app.py &   # then
    python scripts/screenshots.py --url http://localhost:8501 --out screenshots

Fails if the theme switch is not fully visible without scrolling, the page shows an error, or a
theme change does not take effect (the switch is clicked through every mode, twice, including the
already-active button, and the page colours and the pressed button are checked each time).
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


def full_page(page: Page, path: Path) -> None:
    """Streamlit scrolls inside its main container, so grow the viewport to the content height."""
    size = page.viewport_size
    height = page.evaluate(
        "() => Math.max(...[...document.querySelectorAll('[data-testid=stMain], [data-testid=stAppViewContainer]')]"
        ".map(e => e.scrollHeight), document.body.scrollHeight)"
    )
    page.set_viewport_size({"width": size["width"], "height": int(height)})
    page.wait_for_timeout(2000)
    page.screenshot(path=path)
    page.set_viewport_size(size)
    page.wait_for_timeout(500)


PAPER = {"light": "rgb(245, 245, 247)", "dark": "rgb(0, 0, 0)"}


def theme_button(page: Page, label: str):
    return page.frame_locator(".st-key-theme iframe").locator("button").filter(has_text=label).first


def check_theme(page: Page, label: str, expected: str) -> None:
    page.wait_for_timeout(400)
    state = page.evaluate(
        """() => ({
            attr: document.documentElement.getAttribute("data-lx-theme"),
            paper: getComputedStyle(document.querySelector(".stApp")).backgroundColor,
            chart: (() => { const c = document.querySelector('[data-testid="stVegaLiteChart"], [data-testid="stArrowVegaLiteChart"]');
                            return c ? getComputedStyle(c).filter : "none"; })(),
        })"""
    )
    pressed = theme_button(page, label).get_attribute("aria-pressed")
    others = page.frame_locator(".st-key-theme iframe").locator('button[aria-pressed="true"]').count()
    inverted = state["chart"] != "none"
    ok = (state["attr"] == expected and state["paper"] == PAPER[expected] and pressed == "true"
          and others == 1 and inverted == (expected == "dark"))
    print(f"  {label:6} -> {state} pressed={pressed} pressed_count={others} {'OK' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(f"Theme '{label}' did not apply: expected {expected}, got {state}")


CONTRAST_JS = """() => {
  const parse = c => { const m = c.match(/[\\d.]+/g).map(Number); return {r: m[0], g: m[1], b: m[2], a: m.length > 3 ? m[3] : 1}; };
  const lum = ({r, g, b}) => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
                               return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const mix = (c, under) => ({r: c.r * c.a + under.r * (1 - c.a), g: c.g * c.a + under.g * (1 - c.a), b: c.b * c.a + under.b * (1 - c.a), a: 1});
  const bgOf = e => { const layers = []; for (; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor);
                        if (c.a > 0) layers.push(c); if (c.a >= 1) break; }
                      let base = layers.length && layers[layers.length - 1].a >= 1 ? layers.pop() : {r: 255, g: 255, b: 255, a: 1};
                      while (layers.length) base = mix(layers.pop(), base); return base; };
  const bad = [];
  document.querySelectorAll(".stApp *").forEach(e => {
    const text = [...e.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim()).map(n => n.textContent.trim()).join(" ");
    const cs = getComputedStyle(e);
    if (!text || cs.visibility === "hidden" || cs.display === "none" || !e.getClientRects().length) return;
    const bg = bgOf(e), fg = mix(parse(cs.color), bg);
    const ratio = (Math.max(lum(fg), lum(bg)) + .05) / (Math.min(lum(fg), lum(bg)) + .05);
    const large = parseFloat(cs.fontSize) >= 24 || (parseFloat(cs.fontSize) >= 18.6 && +cs.fontWeight >= 700);
    if (ratio < (large ? 3 : 4.5)) bad.push(`${ratio.toFixed(2)} ${e.tagName}.${e.className} "${text.slice(0, 40)}"`);
  });
  return bad;
}"""


def check_contrast(page: Page, mode: str) -> None:
    """Every visible text must be readable (WCAG AA) in this theme."""
    bad = page.evaluate(CONTRAST_JS)
    print(f"  contrast in {mode}: {len(bad)} problems")
    if bad:
        raise SystemExit(f"Low-contrast text in {mode} mode:\n" + "\n".join(bad[:20]))


def cycle_themes(page: Page, system: str) -> None:
    """Click through every mode twice (and the active one again) and check each change applies."""
    print(f"Theme cycle with the system in {system} mode:")
    steps = [("Noche", "dark"), ("Claro", "light"), ("Claro", "light"), ("Auto", system), ("Noche", "dark"),
             ("Noche", "dark"), ("Auto", system), ("Auto", system), ("Claro", "light"), ("Noche", "dark"), ("Auto", system)]
    for label, expected in steps:
        theme_button(page, label).click()
        check_theme(page, label, expected)
    # A theme change must never be animated: background, cards and text change in the same frame.
    duration = page.evaluate('() => getComputedStyle(document.querySelector(".stApp")).transitionDuration')
    if any(float(d.strip().rstrip("s") or 0) > 0 for d in duration.split(",")):
        raise SystemExit(f"The page background animates on theme change ({duration})")
    for label, mode in (("Claro", "light"), ("Noche", "dark")):
        theme_button(page, label).click()
        page.wait_for_timeout(400)
        check_contrast(page, mode)


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
        full_page(desktop, args.out / "light.png")
        theme_button(desktop, "Noche").click()
        desktop.wait_for_timeout(1000)
        desktop.screenshot(path=args.out / "dark-top.png")
        full_page(desktop, args.out / "dark.png")

        cycle_themes(desktop, "light")
        desktop.reload(wait_until="networkidle")  # the choice survives a reload
        ready(desktop, args.url)
        check_theme(desktop, "Auto", "light")

        night = browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme="dark")
        ready(night, args.url)
        check_theme(night, "Auto", "dark")  # Auto follows the system on first visit
        cycle_themes(night, "dark")

        phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, color_scheme="light")
        ready(phone, args.url)
        switch_visible(phone)
        phone.screenshot(path=args.out / "phone.png")
        full_page(phone, args.out / "phone-full.png")
        browser.close()
    print(f"Screenshots in {args.out}")


if __name__ == "__main__":
    main()
