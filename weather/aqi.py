"""PM2.5 concentration to air-quality index, on both scales that matter here.

The same air gets two very different numbers depending on whose scale you use,
and that gap is the point of the toggle on the Beijing page. 35 ug/m3 is the
top of China's *best* band (AQI 50, "excellent") and simultaneously the top of
the US "moderate" band (AQI 100) — one number, two verdicts, a factor of two
apart. So the site computes from the concentration and never stores an index.

US EPA: 40 CFR Part 58 Appendix G, as revised 2024 (the reannounced PM2.5 NAAQS
moved the Good/Moderate break from 12.0 to 9.0). Concentration is truncated to
one decimal before lookup, per the rule.

China: HJ 633-2012, Table 1, the 24-hour PM2.5 column. Concentration is used as
an integer. Note the scale has seven breakpoint rows but six named categories:
201-300 and 301-500 both fall under the two "heavy"/"severe" labels.
"""

# (C_lo, C_hi, I_lo, I_hi, category index)
US_PM25 = [
    (0.0,   9.0,   0,   50,  0),
    (9.1,   35.4,  51,  100, 1),
    (35.5,  55.4,  101, 150, 2),
    (55.5,  125.4, 151, 200, 3),
    (125.5, 225.4, 201, 300, 4),
    (225.5, 325.4, 301, 500, 5),
]

CN_PM25 = [
    (0,   35,  0,   50,  0),
    (35,  75,  51,  100, 1),
    (75,  115, 101, 150, 2),
    (115, 150, 151, 200, 3),
    (150, 250, 201, 300, 4),
    (250, 350, 301, 400, 5),
    (350, 500, 401, 500, 5),
]

# Six categories, in ramp order. `css` is the token the design system defines;
# `band` is the AQI range shown in the legend.
US_CATS = [
    ("Good",                           "0-50",    "--aqi-1"),
    ("Moderate",                       "51-100",  "--aqi-2"),
    ("Unhealthy for sensitive groups", "101-150", "--aqi-3"),
    ("Unhealthy",                      "151-200", "--aqi-4"),
    ("Very unhealthy",                 "201-300", "--aqi-5"),
    ("Hazardous",                      "301+",    "--aqi-6"),
]

CN_CATS = [
    ("Excellent",          "0-50",    "--aqi-1", "优"),
    ("Good",               "51-100",  "--aqi-2", "良"),
    ("Lightly polluted",   "101-150", "--aqi-3", "轻度污染"),
    ("Moderately polluted", "151-200", "--aqi-4", "中度污染"),
    ("Heavily polluted",   "201-300", "--aqi-5", "重度污染"),
    ("Severely polluted",  "301+",    "--aqi-6", "严重污染"),
]

# The concentration at which each scale first calls the air something other than
# its best category. These are the lines the charts draw, because a threshold a
# reader can name beats a gridline they cannot.
US_GOOD_LIMIT = 9.0        # above this the US stops saying "Good"
US_UNHEALTHY = 55.5        # US "Unhealthy" — the level that closes schools
CN_GOOD_LIMIT = 35         # above this China stops saying "excellent"
CN_LIGHT_LIMIT = 75        # China's "lightly polluted" floor
WHO_DAILY = 15.0           # WHO 2021 24-hour guideline
WHO_ANNUAL = 5.0           # WHO 2021 annual guideline
CN_ANNUAL_STD = 35.0       # China's own GB 3095-2012 Grade II annual standard


def _index(conc, table, truncate):
    if conc is None:
        return None
    c = int(conc * 10) / 10.0 if truncate else round(conc)
    top = table[-1]
    if c >= top[1]:
        # Both scales stop at 500. Beyond the top breakpoint the honest answer
        # is "off the scale", not an extrapolated number, so it pins.
        return top[3], top[4]
    for lo, hi, ilo, ihi, cat in table:
        if c <= hi:
            lo_c = max(lo, 0)
            span = hi - lo_c
            frac = 0.0 if span <= 0 else (c - lo_c) / span
            return int(round(ilo + frac * (ihi - ilo))), cat
    return top[3], top[4]


def us_aqi(conc):
    """US EPA AQI for a 24-hour PM2.5 mean. Returns (aqi, category index)."""
    return _index(conc, US_PM25, truncate=True)


def cn_aqi(conc):
    """China HJ 633-2012 IAQI for a 24-hour PM2.5 mean. Returns (aqi, category)."""
    return _index(conc, CN_PM25, truncate=False)


SCALES = {"us": (us_aqi, US_PM25, US_CATS), "cn": (cn_aqi, CN_PM25, CN_CATS)}


def category(conc, scale="us"):
    fn = SCALES[scale][0]
    r = fn(conc)
    return None if r is None else r[1]


def js_payload():
    """The same tables, handed to the page so the toggle is instant and offline.

    Duplicating the breakpoints in JS would be how they drift, so they are
    serialised from the Python that the build already trusts.
    """
    return {
        "us": {
            "bp": [[lo, hi, ilo, ihi, cat] for lo, hi, ilo, ihi, cat in US_PM25],
            "trunc": 1,
            "cats": [{"name": n, "band": b, "css": c} for n, b, c in US_CATS],
            "name": "US EPA",
            "note": "US EPA AQI (40 CFR 58 App. G, 2024 revision)",
            "refs": [{"v": US_GOOD_LIMIT, "label": "Good limit 9"},
                     {"v": US_UNHEALTHY, "label": "Unhealthy 55.5"}],
        },
        "cn": {
            "bp": [[lo, hi, ilo, ihi, cat] for lo, hi, ilo, ihi, cat in CN_PM25],
            "trunc": 0,
            "cats": [{"name": n, "band": b, "css": c, "zh": z} for n, b, c, z in CN_CATS],
            "name": "China",
            "note": "China HJ 633-2012 IAQI, 24-hour PM2.5",
            "refs": [{"v": CN_GOOD_LIMIT, "label": "优 limit 35"},
                     {"v": CN_LIGHT_LIMIT, "label": "良 limit 75"}],
        },
        "who": {"daily": WHO_DAILY, "annual": WHO_ANNUAL},
        "cnAnnual": CN_ANNUAL_STD,
    }
