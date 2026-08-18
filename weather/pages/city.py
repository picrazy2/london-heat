"""The temperature module's payload and its prose.

Every number in a caption is computed. Hand-written ones go stale silently, and
one on the old site already had: "the 1976 record of 20 still stands" survived a
part-year drawing level with it, and nobody noticed for a season.
"""
from ..temps import Record

WORDS = ["no", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
         "Nine", "Ten"]


def _record_of(hist, years, key, cur_year):
    """Holder of the record for `key`, and where the part-year stands.

    The maximum is taken over completed years only, and ties go to the earliest,
    so a part-year that merely draws level does not take the record off the year
    that set it.
    """
    vals = hist[key]
    best, holder = -1, None
    for v, y in zip(vals, years):
        if y != cur_year and v > best:
            best, holder = v, y
    return holder, best, vals[-1]


def captions(rec: Record, hist, dec):
    """One sentence per chart, in the same order the metrics are declared."""
    years, cur = rec.years, rec.cur_year
    out = {}
    m1, m2, n1, n2 = rec.metrics

    # First day threshold: the leader, and how much of the top ten is recent.
    yr, best, now = _record_of(hist, years, m1.key, cur)
    cut = cur - 24
    top = [y for _, y in sorted(zip(hist[m1.key], years), reverse=True)[:10]]
    recent = sum(1 for y in top if y >= cut)
    lead = (f"<b>Part-year {cur} already leads with {now}</b>" if now > best
            else f"<b>{yr} leads with {best}</b>")
    span = f"All ten" if recent == 10 else f"{WORDS[recent]} of the ten"
    out[m1.key] = (f"Rising and noisy — {lead}. "
                   f"{span} highest years fall since {cut}.")

    # Second day threshold: whether the standing record has been reached.
    yr, best, now = _record_of(hist, years, m2.key, cur)
    tail = f"days at {m2.sub.replace('≥ ', '')} or above are now routine where they were once rare."
    if now > best:
        out[m2.key] = (f"<b>Part-year {cur} leads with {now}</b>, a new all-time high — {tail}")
    elif now == best:
        out[m2.key] = (f"The <b>{yr} record of {best}</b> stood for {cur - yr} years, and "
                       f"part-year {cur} has now matched it. {tail.capitalize()}")
    else:
        out[m2.key] = f"The <b>{yr} record of {best}</b> still stands, but {tail}"

    # First night threshold: the climb, read off the first and last decade means.
    decs = sorted(dec["avg"], key=int)
    if decs:
        f, l = decs[0], decs[-1]
        out[n1.key] = (f"The steadiest climb of the four — from about "
                       f"{round(dec['avg'][f][n1.key])} a year in the {f}s to "
                       f"<b>about {round(dec['avg'][l][n1.key])} in the {l}s</b>.")
    else:
        out[n1.key] = ""

    # Second night threshold: still rare enough that the record is a small count.
    yr, best, now = _record_of(hist, years, n2.key, cur)
    if now > best:
        out[n2.key] = (f"Genuinely rare even now. <b>Part-year {cur} leads at {now}</b> "
                       f"— a new all-time high, past {yr}'s {best}.")
    elif now == best:
        out[n2.key] = (f"Genuinely rare even now. <b>{yr} holds the record at {best}</b>, "
                       f"and part-year {cur} has already matched it.")
    else:
        out[n2.key] = (f"Genuinely rare even now. <b>{yr} holds the record at {best}</b>; "
                       f"{cur} so far has {now}.")
    return out


def payload(rec: Record, city, slug, source_html, y_range):
    """Everything templates/temp.js needs, for either city."""
    hist = rec.hist()
    dec = rec.decades()
    return {
        "city": city,
        "slug": slug,
        "baseline": list(rec.baseline),
        "metrics": [m.as_dict() for m in rec.metrics],
        "hist": hist,
        "monthly": rec.monthly(),
        "all": rec.daily(),
        "captions": captions(rec, hist, dec),
        "source": source_html,
        "yMin": y_range[0],
        "yMax": y_range[1],
    }
