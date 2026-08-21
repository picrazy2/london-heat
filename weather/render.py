"""Turning a template fragment into a real, servable HTML document.

Templates are bare fragments — a <title>, a <style>, then markup — because they
began life as Claude artifacts, which supplied the document skeleton. Served as
files they need one: without a charset the degree signs mojibake, and without a
viewport phones render everything at desktop width.

This module supplies the skeleton, the shared stylesheet, the theme boot script,
the social metadata and the dock, so a template only ever has to describe its
own page.
"""
import html
import json
import os

from . import design

PAGES = {
    "/": ("Weather — London and Beijing, measured",
          "Live air quality in Beijing and the long temperature record in both "
          "cities, from the instruments themselves. Updated every day."),
    "/london": ("London — Heathrow's warming record",
                "Hot days and tropical nights at London Heathrow since 1960, counted "
                "from the airport's own thermometer. Updated daily."),
    "/beijing": ("Beijing — heat and air quality",
                 "Beijing's summers against its own record, and PM2.5 from the city's "
                 "monitoring network on both the US EPA and Chinese scales. Updated daily."),
}

SOCIAL_ALT = {
    "/": "Two panels: London's hot days per year rising since 1960, and Beijing's "
         "PM2.5 falling since 2014",
    "/london": "Hot days per year at Heathrow, 1960 to today, as a deviation from the "
               "1961-90 average: mostly below it early on, almost entirely above it "
               "since the 1990s",
    "/beijing": "Beijing's annual mean PM2.5 from 2014 to today, falling from far above "
                "China's own standard to close to it, and still far above the WHO guideline",
}


def esc(s):
    return html.escape(str(s), quote=True)


def j(o):
    """Compact JSON, safe to drop inside a <script> block."""
    return (json.dumps(o, separators=(",", ":"), ensure_ascii=False)
            .replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


HEAD_ICONS = (
    '<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n'
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">\n'
    '<link rel="manifest" href="/site.webmanifest">\n'
    '<meta name="theme-color" content="#f4f3f7" media="(prefers-color-scheme: light)">\n'
    '<meta name="theme-color" content="#0b0b12" media="(prefers-color-scheme: dark)">\n'
)


def social(path, stamp, image="social.png"):
    if path not in PAGES:
        return ""
    title, desc = PAGES[path]
    url = design.SITE_URL + ("" if path == "/" else path)
    img = f"{design.SITE_URL}/{image}?v={stamp}"     # ?v= busts scrapers' caches
    tags = [
        f'<meta name="description" content="{esc(desc)}">',
        f'<link rel="canonical" href="{esc(url)}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{esc(design.SITE_NAME)}">',
        f'<meta property="og:title" content="{esc(title)}">',
        f'<meta property="og:description" content="{esc(desc)}">',
        f'<meta property="og:url" content="{esc(url)}">',
        f'<meta property="og:image" content="{esc(img)}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{esc(SOCIAL_ALT[path])}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{esc(title)}">',
        f'<meta name="twitter:description" content="{esc(desc)}">',
        f'<meta name="twitter:image" content="{esc(img)}">',
    ]
    return "\n".join(tags) + "\n"


def document(fragment, path=None, stamp="", image="social.png", head_extra="", body_extra=""):
    """Wrap a fragment in a document: skeleton, stylesheet, chrome, scripts."""
    i = fragment.find("</style>")
    if i == -1:
        title_html, page_css, body = "", "", fragment
    else:
        o = fragment.find("<style>")
        title_html, page_css, body = fragment[:o], fragment[o + 7:i], fragment[i + 8:]

    if path is not None:
        marker = '<div class="wrap">'
        if marker not in body:
            raise SystemExit(f"{path}: template has no .wrap container to hang chrome on")
        body = body + design.dock(path)

    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f'{HEAD_ICONS}{social(path, stamp, image)}{title_html}'
        f'<script>{design.THEME_BOOT}</script>\n'
        f'<script>{design.CHROME_JS}</script>\n'
        f'<style>{design.css()}{page_css}</style>\n{head_extra}'
        f'</head>\n<body>{body}\n'
        f'<script>{design.THEME_JS}</script>\n{body_extra}</body>\n</html>\n'
    )


def emit(out_dir, name, text, **kw):
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
        f.write(document(text, **kw))


MANIFEST = {
    "name": "Weather — London and Beijing",
    "short_name": "Weather",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#f4f3f7",
    "theme_color": "#5e5ce6",
    "icons": [
        {"src": "/favicon.svg", "type": "image/svg+xml", "sizes": "any", "purpose": "any"},
        {"src": "/apple-touch-icon.png", "type": "image/png", "sizes": "180x180"},
    ],
}
