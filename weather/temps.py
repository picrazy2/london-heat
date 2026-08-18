"""Everything the temperature pages count, for any city.

London and Beijing ask the same four questions of their thermometers — how many
hot days, how many very hot days, how many mild nights, how many hot nights —
and only the thresholds differ. So the analysis lives here once and is
parameterised, rather than being copied per city, which is how the two London
pages had already drifted apart before this rewrite.

Thresholds are not arbitrary in either city. London's 25/30 are the round
numbers the Met Office narrates summers with. Beijing's 35 is the China
Meteorological Administration's own high-temperature warning line, and 30 is the
level below it that separates a warm day from a hot one in a continental summer
where 25 is unremarkable for four months of the year.
"""
import calendar
import statistics as st
from collections import defaultdict
from datetime import date

MABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def doy(y, m, d):
    return (date(y, m, d) - date(y, 1, 1)).days + 1


def ymd(s):
    s = s.replace("-", "")
    return int(s[:4]), int(s[4:6]), int(s[6:8])


def fmt_short(s):
    _, m, d = ymd(s)
    return f"{d} {MABBR[m - 1]}"


def fmt_long(s):
    y, m, d = ymd(s)
    return f"{d} {MABBR[m - 1]} {y}"


class Metric:
    """One counted threshold: which series it reads, and how it is labelled."""

    def __init__(self, key, label, sub, series, thr, css, unit):
        self.key, self.label, self.sub = key, label, sub
        self.series, self.thr, self.css, self.unit = series, thr, css, unit

    def as_dict(self):
        return {"key": self.key, "label": self.label, "sub": self.sub,
                "css": self.css, "unit": self.unit, "thr": self.thr,
                "series": self.series}


class Record:
    """A city's daily maxima and minima, and every aggregate drawn from them."""

    def __init__(self, tx, tn, metrics, first_year, cur_date, baseline=(1961, 1990),
                 filled=frozenset()):
        self.tx, self.tn = tx, tn
        self.metrics = metrics
        self.cur_date = cur_date                    # 'YYYYMMDD', last complete day
        self.cur_year = int(cur_date[:4])
        self.baseline = baseline
        self.filled = filled

        by_year_x, by_year_n = defaultdict(dict), defaultdict(dict)
        for k, v in tx.items():
            by_year_x[int(k[:4])][doy(*ymd(k))] = v
        for k, v in tn.items():
            by_year_n[int(k[:4])][doy(*ymd(k))] = v
        self.dx, self.dn = by_year_x, by_year_n

        # A year is in the record if it is essentially complete, or if it is the
        # year still running. 200 days is loose on purpose: it admits a year with
        # a genuine outage and excludes the first fragment of a station's life.
        self.years = sorted(y for y in by_year_x
                            if len(by_year_x[y]) >= 200 or y == self.cur_year)
        self.years = [y for y in self.years if y >= first_year]

    # ── helpers ────────────────────────────────────────────────────────────
    def _vals(self, metric):
        return self.tx if metric.series == "max" else self.tn

    def _counts(self, metric, cut_md=None):
        vals = self._vals(metric)
        c = {y: 0 for y in self.years}
        for k, v in vals.items():
            y = int(k[:4])
            if y in c and v >= metric.thr and (cut_md is None or k[4:8] <= cut_md):
                c[y] += 1
        return [c[y] for y in self.years]

    def _streaks(self, metric, cut_md=None):
        """Longest run of consecutive qualifying days in each year."""
        vals = self._vals(metric)
        by_year = defaultdict(list)
        for k in vals:
            by_year[int(k[:4])].append(k)
        out = []
        for y in self.years:
            best = run = 0
            prev = None
            for k in sorted(k for k in by_year[y] if cut_md is None or k[4:8] <= cut_md):
                d = date(*ymd(k))
                if vals[k] >= metric.thr:
                    run = run + 1 if (prev and (d - prev).days == 1) else 1
                    prev, best = d, max(best, run)
                else:
                    run, prev = 0, None
            out.append(best)
        return out

    # ── the annual bar charts ──────────────────────────────────────────────
    def hist(self):
        cut_md = self.cur_date[4:8]
        h = {"years": self.years, "partial": self.cur_year,
             "ytd": fmt_short(self.cur_date)}
        for m in self.metrics:
            h[m.key] = self._counts(m)
            h[m.key + "y"] = self._counts(m, cut_md)
            h[m.key + "s"] = self._streaks(m)
            h[m.key + "sy"] = self._streaks(m, cut_md)
        return h

    # ── decade profiles, for the explorer's backdrop ───────────────────────
    def decades(self, nweeks=52):
        cov = defaultdict(int)
        for k in self.tx:
            cov[int(k[:4])] += 1
        # Complete years only, and never the year still running: a part-year can
        # contribute days up to today but none after it, which tilts every
        # seasonal distribution earlier.
        good = {y for y in cov if cov[y] >= 350 and y < self.cur_year and y in self.years}
        wk = lambda d: min(nweeks - 1, (d - 1) // 7)                       # noqa: E731
        wmax = defaultdict(lambda: defaultdict(list))
        wmin = defaultdict(lambda: defaultdict(list))
        per_year = defaultdict(lambda: [0] * len(self.metrics))
        for k, v in self.tx.items():
            y = int(k[:4])
            if y not in good:
                continue
            wmax[(y // 10) * 10][wk(doy(*ymd(k)))].append(v)
            for i, m in enumerate(self.metrics):
                if m.series == "max" and v >= m.thr:
                    per_year[y][i] += 1
        for k, v in self.tn.items():
            y = int(k[:4])
            if y not in good:
                continue
            wmin[(y // 10) * 10][wk(doy(*ymd(k)))].append(v)
            for i, m in enumerate(self.metrics):
                if m.series == "min" and v >= m.thr:
                    per_year[y][i] += 1
        decs = sorted(wmax)
        out = {"decades": [str(d) for d in decs],
               "weeks": [w * 7 + 4 for w in range(nweeks - 1)] + [361],
               "weekmax": {}, "weekmin": {}, "avg": {}}
        mean = lambda a: round(sum(a) / len(a), 2) if a else None           # noqa: E731
        for dec in decs:
            out["weekmax"][str(dec)] = [mean(wmax[dec][w]) for w in range(nweeks)]
            out["weekmin"][str(dec)] = [mean(wmin[dec][w]) for w in range(nweeks)]
            ys = [y for y in per_year if (y // 10) * 10 == dec]
            avg = {"nyears": len(ys)}
            for i, m in enumerate(self.metrics):
                avg[m.key] = round(st.mean(per_year[y][i] for y in ys), 1) if ys else 0
            out["avg"][str(dec)] = avg
        self.good_years = good
        return out

    # ── the daily explorer ─────────────────────────────────────────────────
    def daily(self):
        out = {}
        for y in self.years:
            dm, dn = self.dx[y], self.dn.get(y, {})
            if not dm:
                continue
            s, e = min(dm), max(dm)
            out[str(y)] = {"s": s,
                           "x": [dm.get(i) for i in range(s, e + 1)],
                           "n": [dn.get(i) for i in range(s, e + 1)]}
        return out

    # ── monthly and annual means ───────────────────────────────────────────
    def monthly(self):
        mx, mn, mb = defaultdict(list), defaultdict(list), defaultdict(list)
        for k, v in self.tx.items():
            mx[(int(k[:4]), int(k[4:6]))].append(v)
        for k, v in self.tn.items():
            mn[(int(k[:4]), int(k[4:6]))].append(v)
        for k in set(self.tx) & set(self.tn):
            mb[(int(k[:4]), int(k[4:6]))].append((self.tx[k] + self.tn[k]) / 2)

        # Two decimals, not one. The page shows a month at 0.1 C, but ranking on
        # the displayed figure invents ties — two Julys 0.06 C apart both read
        # 22.4 and both came first. Daily values land on a 0.1 C grid, so a
        # month's mean is meaningful to about 0.003 C; 2dp separates all but the
        # months that really are level, and those keep their shared rank.
        def avg(store, y, m):
            v = store.get((y, m))
            if not v or len(v) < calendar.monthrange(y, m)[1] - 2:
                return None
            return round(sum(v) / len(v), 2)

        out = {"years": self.years, "cur": self.cur_year, "hi": {}, "lo": {}, "avg": {}}
        for m in range(1, 13):
            out["hi"][str(m)] = [avg(mx, y, m) for y in self.years]
            out["lo"][str(m)] = [avg(mn, y, m) for y in self.years]
            out["avg"][str(m)] = [avg(mb, y, m) for y in self.years]

        # The most recent month that has actually finished. It anchors the
        # carousel and decides which year each card highlights: a December card
        # read in February must point at the December just gone, not this year's.
        ly, lm, ld = ymd(self.cur_date)
        if ld == calendar.monthrange(ly, lm)[1]:
            ay, am = ly, lm
        elif lm > 1:
            ay, am = ly, lm - 1
        else:
            ay, am = ly - 1, 12
        out["ay"], out["am"] = ay, am

        out["part"] = None
        if (ly, lm) != (ay, am) and mb.get((ly, lm)):
            m1 = lambda s: round(sum(s[(ly, lm)]) / len(s[(ly, lm)]), 2) if s.get((ly, lm)) else None  # noqa: E731
            out["part"] = {"y": ly, "m": lm, "days": len(mb[(ly, lm)]),
                           "through": fmt_short(self.cur_date),
                           "avg": m1(mb), "hi": m1(mx), "lo": m1(mn)}

        yx, yn, yb = defaultdict(list), defaultdict(list), defaultdict(list)
        for k, v in self.tx.items():
            yx[int(k[:4])].append(v)
        for k, v in self.tn.items():
            yn[int(k[:4])].append(v)
        for k in set(self.tx) & set(self.tn):
            yb[int(k[:4])].append((self.tx[k] + self.tn[k]) / 2)

        def yavg(store, y):
            v = store.get(y)
            return round(sum(v) / len(v), 1) if v and len(v) >= 350 else None

        out["ann"] = {"hi": [yavg(yx, y) for y in self.years],
                      "lo": [yavg(yn, y) for y in self.years],
                      "avg": [yavg(yb, y) for y in self.years]}
        return out

    # ── when in the year each threshold happens ────────────────────────────
    def season(self):
        good = getattr(self, "good_years", None)
        if good is None:
            self.decades()
            good = self.good_years

        def smooth(a, w):
            n = len(a)
            return [sum(a[max(0, i - w):min(n, i + w + 1)]) / (min(n, i + w + 1) - max(0, i - w))
                    for i in range(n)]

        out = {}
        for m in self.metrics:
            vals = self._vals(m)
            bd, bm = [0] * 366, [0] * 13
            for k, v in vals.items():
                if int(k[:4]) in good and v >= m.thr:
                    bd[doy(*ymd(k))] += 1
                    bm[int(k[4:6])] += 1
            series = bd[1:366]
            # Peak of the *smoothed* curve, using the same kernel the page draws
            # with. A raw argmax is meaningless on a thin series: when 25 events
            # are spread over 60 years the busiest single day holds two of them
            # and is picked by tie-break, landing weeks from the drawn peak.
            sm = smooth(series, 4)
            out[m.key] = {"doy": series, "pk": max(range(365), key=lambda i: sm[i]) + 1,
                          "tot": sum(bd), "mon": bm[1:13], "ny": len(good)}
        return out

    # ── the headline figures on the hero ───────────────────────────────────
    def summary(self):
        h = self.hist()
        i = self.years.index(self.cur_year) if self.cur_year in self.years else -1
        b0, b1 = self.baseline
        out = {"year": self.cur_year, "through": fmt_short(self.cur_date), "metrics": []}
        for m in self.metrics:
            vals, ytd = h[m.key], h[m.key + "y"]
            try:
                j0, j1 = self.years.index(b0), self.years.index(b1)
                normal = sum(ytd[j0:j1 + 1]) / (j1 - j0 + 1)
            except ValueError:
                normal = sum(ytd) / len(ytd)
            best = max(v for v, y in zip(vals, self.years) if y != self.cur_year)
            rank = 1 + sum(1 for v in ytd if v > ytd[i])
            out["metrics"].append({
                "key": m.key, "label": m.label, "sub": m.sub, "css": m.css,
                "unit": m.unit, "now": ytd[i], "normal": round(normal, 1),
                "rank": rank, "n": len(self.years), "record": best,
            })
        return out
