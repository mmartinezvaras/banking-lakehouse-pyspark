"""Marcos's "Apple Style" palette (monochrome: black ink is the accent in light mode, white in
night mode) as CSS custom properties over Streamlit, plus matching colours for the charts."""

NEGRO, GRAFITO, PLATA, INDIGO, BLANCO = "#000000", "#555555", "#86868B", "#F5F5F7", "#FFFFFF"

LIGHT = {
    "paper": INDIGO,
    "sheet": BLANCO,
    "ink": NEGRO,
    "ink-2": GRAFITO,
    "rule": "rgba(134, 134, 139, 0.35)",
    "accent": NEGRO,
    "accent-soft": INDIGO,
    "mark": "rgba(134, 134, 139, 0.28)",
    "ring": "rgba(0, 0, 0, 0.08)",
    "halo": "rgba(0, 0, 0, 0.12)",
    "lift": "0 1px 2px rgba(0, 0, 0, 0.04), 0 4px 16px -6px rgba(0, 0, 0, 0.10)",
}
DARK = {
    "paper": NEGRO,
    "sheet": "#141414",
    "ink": INDIGO,
    "ink-2": PLATA,
    "rule": "rgba(134, 134, 139, 0.30)",
    "accent": BLANCO,
    "accent-soft": "rgba(255, 255, 255, 0.10)",
    "mark": "rgba(134, 134, 139, 0.35)",
    "ring": "rgba(255, 255, 255, 0.10)",
    "halo": "rgba(255, 255, 255, 0.20)",
    "lift": "0 1px 2px rgba(0, 0, 0, 0.5), 0 6px 20px -8px rgba(0, 0, 0, 0.8)",
}

# Chart colours: three tones of ink, never colour alone (shapes and labels carry the meaning).
CHART = {
    "light": {"ink": NEGRO, "mid": GRAFITO, "soft": PLATA, "grid": "#E4E4E8", "label": GRAFITO},
    "dark": {"ink": BLANCO, "mid": PLATA, "soft": GRAFITO, "grid": "#2A2A2A", "label": PLATA},
}

FONTS = (
    "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
    "&display=swap"
)

ICONS = {
    "description": '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "inventory_2": '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4"/>',
    "cleaning_services": '<path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z"/><path d="M18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8z"/>',
    "insights": '<path d="M3 20h18"/><path d="M5 16l4-5 4 3 6-8"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
    "arrow_forward": '<path d="M4 12h16M14 6l6 6-6 6"/>',
    "code": '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5"/>',
}


def _icon_css() -> str:
    from urllib.parse import quote

    out = []
    for name, paths in ICONS.items():
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" '
               f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')
        out.append(f'.ic-{name}{{--ic:url("data:image/svg+xml,{quote(svg)}");}}')
    return "".join(out)


def _vars(tokens: dict) -> str:
    return "".join(f"--lx-{k}:{v};" for k, v in tokens.items())


def page_css(mode: str) -> str:
    light, dark = f":root{{{_vars(LIGHT)}color-scheme:light;}}", f":root{{{_vars(DARK)}color-scheme:dark;}}"
    tokens = dark if mode == "dark" else light + (f"@media (prefers-color-scheme: dark){{{dark}}}" if mode == "auto" else "")
    return f"<style>@import url('{FONTS}');{tokens}{CSS}{_icon_css()}</style>"


CSS = """
:root { --lx-ease: cubic-bezier(0.23, 1, 0.32, 1); }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background: var(--lx-paper); color: var(--lx-ink);
  font-family: "Inter", system-ui, -apple-system, sans-serif;
  transition: background-color 250ms ease, color 250ms ease;
}
[data-testid="stHeader"] { background: transparent; }
.stApp p, .stApp li, .stApp label, .stApp span:where(:not(.ic):not([data-testid="stIconMaterial"])), .stApp a, [data-testid="stMarkdownContainer"] { color: var(--lx-ink); font-family: "Inter", system-ui, sans-serif; }
.stApp [data-testid="stIconMaterial"] { color: inherit !important; }
[data-testid="stCaptionContainer"] p { color: var(--lx-ink-2); }
.stApp a { color: var(--lx-accent); text-decoration: underline; text-decoration-color: var(--lx-rule);
  text-underline-offset: 3px; transition: text-decoration-color 150ms ease; }
@media (hover: hover) and (pointer: fine) { .stApp a:hover { text-decoration-color: var(--lx-accent); } }
[data-testid="stMainBlockContainer"] { max-width: 1080px; padding-top: 2.5rem; }

/* Theme switch: one pill, right-aligned, never scrolls */
.st-key-theme { display: flex; justify-content: flex-end; width: 100%; }
.st-key-theme > div, .st-key-theme [data-testid="stButtonGroup"] { width: auto !important; max-width: 100%; overflow: visible !important; }
.st-key-theme [data-testid="stButtonGroup"] {
  display: inline-flex; flex-wrap: nowrap; gap: 2px; padding: 3px; background: var(--lx-sheet);
  border-radius: 999px; box-shadow: 0 0 0 1px var(--lx-ring), var(--lx-lift);
}
.st-key-theme [data-testid="stButtonGroup"] div:not(button div) { overflow: visible !important; flex-wrap: nowrap !important; width: auto !important; gap: 2px; }
.st-key-theme button {
  flex: 0 0 auto; white-space: nowrap; min-height: 0; margin: 0 !important; padding: .32rem .8rem !important;
  border: 0 !important; border-radius: 999px !important; background: transparent; color: var(--lx-ink); font-size: .85rem;
  transition: background-color 200ms var(--lx-ease), transform 160ms var(--lx-ease);
}
.st-key-theme button:active { transform: scale(.97); }
.st-key-theme button p, .st-key-theme button span { color: inherit; }
[data-testid="stBaseButton-segmented_controlActive"], .st-key-theme button[aria-checked="true"] {
  background: var(--lx-accent) !important;
}
[data-testid="stBaseButton-segmented_controlActive"], [data-testid="stBaseButton-segmented_controlActive"] p,
[data-testid="stBaseButton-segmented_controlActive"] span, .st-key-theme button[aria-checked="true"] p {
  color: var(--lx-sheet) !important;
}
@media (hover: hover) and (pointer: fine) {
  .st-key-theme button:not([data-testid="stBaseButton-segmented_controlActive"]):hover { background: var(--lx-ring); }
}
.st-key-theme button:focus-visible, .stApp a:focus-visible { outline: none; box-shadow: 0 0 0 4px var(--lx-halo) !important; }

.ic { display: inline-block; width: 1.15em; height: 1.15em; vertical-align: -0.2em; margin-right: .4em;
  background-color: currentColor; -webkit-mask: var(--ic) center / contain no-repeat; mask: var(--ic) center / contain no-repeat; }
.lx-travel .ic { width: 1.5rem; height: 1.5rem; margin: 0; color: var(--lx-ink-2); }
[data-testid="stBaseButton-segmented_controlActive"] [data-testid="stIconMaterial"] { color: var(--lx-sheet) !important; }

/* Rule comparison: plain HTML bars, labelled directly (tone + label, never colour alone) */
.lx-bargroups { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1.4rem; }
.lx-bars .h { font-size: .82rem; font-weight: 600; color: var(--lx-ink-2); margin-bottom: .55rem; }
.lx-bar { display: grid; grid-template-columns: 8.5rem 1fr 3.4rem; align-items: center; gap: .6rem; margin: .4rem 0; font-size: .85rem; }
.lx-bar .who { color: var(--lx-ink-2); white-space: nowrap; }
.lx-bar.window .who { color: var(--lx-ink); font-weight: 600; }
.lx-bar .track { height: 10px; border-radius: 999px; background: var(--lx-ring); overflow: hidden; }
.lx-bar .fill { display: block; height: 100%; width: var(--w); border-radius: inherit; background: var(--lx-ink-2);
  transform-origin: left; animation: lx-grow 600ms var(--lx-ease) both; animation-delay: 120ms; }
.lx-bar.naive .fill { background: var(--lx-rule); }
.lx-bar.window .fill { background: var(--lx-accent); }
.lx-bar .val { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }
@keyframes lx-grow { from { transform: scaleX(0.02); } }
.lx-table td.num { white-space: nowrap; }

/* Hero */
.lx-hero h1 { font-size: clamp(2rem, 4.4vw, 3rem); font-weight: 700; letter-spacing: -0.035em; line-height: 1.05;
  margin: .2rem 0 .8rem; color: var(--lx-ink); }
.lx-hero p { font-size: 1.08rem; line-height: 1.55; color: var(--lx-ink-2); max-width: 64ch; margin: 0; }
.lx-hero p b { color: var(--lx-ink); font-weight: 600; }

/* KPI strip */
.lx-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .9rem; margin: 2rem 0 1rem; }
.lx-kpi { background: var(--lx-sheet); border-radius: 16px; padding: 1.1rem 1.2rem; box-shadow: 0 0 0 1px var(--lx-ring), var(--lx-lift); }
.lx-kpi .v { font-size: 1.9rem; font-weight: 700; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; color: var(--lx-ink); line-height: 1.1; }
.lx-kpi .l { font-size: .86rem; color: var(--lx-ink-2); margin-top: .35rem; line-height: 1.35; }
.lx-kpi .c { font-size: .78rem; color: var(--lx-ink-2); margin-top: .45rem; padding-top: .45rem; border-top: 1px solid var(--lx-rule); }

/* Sections */
.lx-sec { margin: 3.2rem 0 1rem; }
.lx-sec h2 { font-size: 1.55rem; font-weight: 700; letter-spacing: -0.025em; margin: 0 0 .4rem; color: var(--lx-ink); }
.lx-sec p { color: var(--lx-ink-2); font-size: 1rem; line-height: 1.55; max-width: 70ch; margin: 0; }
.lx-card { background: var(--lx-sheet); border-radius: 16px; padding: 1.1rem 1.25rem; box-shadow: 0 0 0 1px var(--lx-ring), var(--lx-lift); margin: .6rem 0; }

/* Layer flow */
.lx-flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .6rem; margin: 1.2rem 0 .4rem; }
.lx-step { background: var(--lx-sheet); border-radius: 14px; padding: .95rem 1rem; box-shadow: 0 0 0 1px var(--lx-ring); position: relative; }
.lx-step .n { font-size: .78rem; font-weight: 600; color: var(--lx-ink-2); }
.lx-step .t { font-size: 1.02rem; font-weight: 600; color: var(--lx-ink); margin: .15rem 0 .35rem; }
.lx-step .v { font-size: 1.35rem; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--lx-ink); }
.lx-step .d { font-size: .82rem; color: var(--lx-ink-2); line-height: 1.4; margin-top: .3rem; }

/* Tables */
.lx-table { width: 100%; border-collapse: collapse; font-size: .9rem; font-variant-numeric: tabular-nums; }
.lx-table th { text-align: left; font-weight: 600; color: var(--lx-ink-2); font-size: .8rem; padding: .5rem .6rem; border-bottom: 1px solid var(--lx-rule); }
.lx-table td { padding: .55rem .6rem; border-bottom: 1px solid var(--lx-rule); color: var(--lx-ink); vertical-align: top; }
.lx-table tr:last-child td { border-bottom: 0; }
.lx-table td.num, .lx-table th.num { text-align: right; }
.lx-table td { transition: background-color 150ms ease; }
.lx-table tr.is-fraud td { background: var(--lx-mark); }
@media (hover: hover) and (pointer: fine) { .lx-table tbody tr:not(.is-fraud):hover td { background: var(--lx-ring); } }
.lx-table .best { font-weight: 700; }
.lx-scroll { overflow-x: auto; }
.lx-tag { display: inline-flex; align-items: center; border-radius: 999px; padding: .05rem .5rem; font-size: .76rem; font-weight: 600;
  border: 1px solid var(--lx-ink); color: var(--lx-ink); white-space: nowrap; }
.lx-tag.solid { background: var(--lx-accent); color: var(--lx-sheet); border-color: var(--lx-accent); }
.lx-tag.ghost { border-color: var(--lx-rule); color: var(--lx-ink-2); }
.lx-note { font-size: .86rem; color: var(--lx-ink-2); margin-top: .6rem; line-height: 1.5; }

/* Delta history */
.lx-versions { list-style: none; margin: 0; padding: 0; }
.lx-versions li { display: grid; grid-template-columns: 3.2rem 10rem 1fr; gap: .6rem; padding: .55rem 0; border-bottom: 1px solid var(--lx-rule); font-size: .92rem; }
.lx-versions li:last-child { border-bottom: 0; }
.lx-versions .ver { font-weight: 700; font-variant-numeric: tabular-nums; }
.lx-versions .op { font-weight: 600; }
.lx-versions .m { color: var(--lx-ink-2); }
.lx-travel { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; font-variant-numeric: tabular-nums; }
.lx-travel .amt { font-size: 1.7rem; font-weight: 700; letter-spacing: -0.02em; }
.lx-travel .old { color: var(--lx-ink-2); text-decoration: line-through; text-decoration-thickness: 2px; }

/* One orchestrated entrance on page load: hero, then the KPI strip in a 50 ms cascade.
   Seen once per visit, so it may run a little longer than interaction feedback (still < 400 ms). */
.lx-hero { animation: lx-in 360ms var(--lx-ease) both; }
.lx-kpi { animation: lx-in 360ms var(--lx-ease) both; animation-delay: calc(80ms + var(--i, 0) * 50ms); }
@keyframes lx-in { from { opacity: 0; transform: translateY(8px); } }
@keyframes lx-fade { from { opacity: 0; } }
/* Reduced motion: keep the fade (it helps orientation), drop the movement */
@media (prefers-reduced-motion: reduce) {
  .lx-hero, .lx-kpi { animation-name: lx-fade; animation-duration: 200ms; }
  .lx-bar .fill { animation: none; }
}

@media (max-width: 760px) {
  .lx-kpis, .lx-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .lx-bargroups { grid-template-columns: 1fr; }
  .lx-versions li { grid-template-columns: 2.6rem 6rem 1fr; }
}
"""
