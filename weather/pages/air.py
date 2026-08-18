"""The air-quality module's payload.

Nothing here computes an index. The page is handed concentrations and the two
breakpoint tables, and derives every AQI in the browser — which is what makes
the scale toggle instantaneous and, more to the point, guarantees the two scales
are judging the same numbers rather than two separately-rounded ones.
"""
from collections import defaultdict
from datetime import datetime

from .. import aqi
from ..sources import pm25

# Station names are published as an optional district prefix plus a site name,
# and the prefix is not decoration: three different stations are called 新城
# ("new town"), and dropping 密云 / 怀柔 / 平谷 would render all three
# identically in a list whose whole job is telling them apart. So the two halves
# are romanised separately and rejoined. The Chinese name is shown beside the
# English one rather than replaced by it.
DISTRICT_EN = {
    "东城": "Dongcheng", "西城": "Xicheng", "朝阳": "Chaoyang", "海淀": "Haidian",
    "丰台": "Fengtai", "石景山": "Shijingshan", "门头沟": "Mentougou",
    "房山": "Fangshan", "通州": "Tongzhou", "顺义": "Shunyi", "昌平": "Changping",
    "大兴": "Daxing", "怀柔": "Huairou", "平谷": "Pinggu", "密云": "Miyun",
    "延庆": "Yanqing",
}

SITE_EN = {
    "万寿西宫": "Wanshouxigong", "东四": "Dongsi", "天坛": "Tiantan",
    "农展馆": "Nongzhanguan", "官园": "Guanyuan", "万柳": "Wanliu",
    "四季青": "Sijiqing", "奥体中心": "Olympic Centre", "古城": "Gucheng",
    "老山": "Laoshan", "八角": "Bajiao", "良乡": "Liangxiang", "燕山": "Yanshan",
    "黄村": "Huangcun", "旧宫": "Jiugong", "亦庄开发区": "Yizhuang",
    "永顺": "Yongshun", "东关": "Dongguan", "新华": "Xinhua",
    "双峪": "Shuangyu", "三家店": "Sanjiadian", "小屯": "Xiaotun",
    "云岗": "Yungang", "花园": "Garden", "南邵": "Nanshao", "北小营": "Beixiaoying",
    "石河营": "Shiheying", "夏都": "Xiadu", "百泉": "Baiquan",
    "水库": "Reservoir", "定陵(对照点)": "Dingling (control site)",
    "定陵": "Dingling", "京东南区域点": "SE regional site",
    "新城": "New Town", "镇": "Town",
}


def _en(name):
    """'密云新城' -> 'Miyun New Town'. Falls back to the Chinese, never to a guess."""
    if not name:
        return None
    district, rest = "", name
    for zh in sorted(DISTRICT_EN, key=len, reverse=True):
        if name.startswith(zh) and len(name) > len(zh):
            district, rest = DISTRICT_EN[zh], name[len(zh):]
            break
    site = SITE_EN.get(rest)
    if site is None:
        # An unknown site keeps its Chinese name; a romanisation invented here
        # would be worse than the real thing sitting next to it.
        return f"{district} {rest}".strip() if district else name
    return f"{district} {site}".strip()


def payload(hourly, live, source_html, map_note):
    daily = pm25.daily_stats(hourly)
    days = sorted(daily)
    cur_year = int(days[-1][:4]) if days else None

    # Annual means, over days complete enough to carry one. "Partial" means the
    # year has not finished — not that it has gaps. A finished year missing forty
    # scattered days to the completeness rule is still a finished year, and
    # fading it in the chart would say something untrue about it.
    by_year = defaultdict(list)
    for d in days:
        by_year[int(d[:4])].append(daily[d]["mean"])
    def carries_a_mean(y):
        # A finished year needs most of itself. The year still running is shown
        # from a couple of months in, faded, because "how is this year going" is
        # the question the chart is most often opened to answer.
        n = len(by_year[y])
        return n >= 250 or (y == cur_year and n >= 45)

    annual = []
    for y in sorted(by_year):
        if not carries_a_mean(y):
            continue
        vals = by_year[y]
        annual.append({"y": y, "mean": round(sum(vals) / len(vals), 1),
                       "n": len(vals), "partial": y == cur_year})

    # Every daily mean, grouped by year, so the browser can re-band them on the
    # fly when the scale changes. ~4,600 numbers; smaller than one chart's JS.
    by_year_days = [{"y": y, "d": [round(v, 1) for v in by_year[y]]}
                    for y in sorted(by_year) if carries_a_mean(y)]

    # Year x month grid.
    mgrid = defaultdict(lambda: defaultdict(list))
    for d in days:
        mgrid[int(d[:4])][int(d[4:6])].append(daily[d]["mean"])
    myears = sorted(mgrid)
    monthly = {
        "years": myears,
        "v": [[round(sum(mgrid[y][m]) / len(mgrid[y][m]), 1)
               if len(mgrid[y].get(m, [])) >= 20 else None
               for m in range(1, 13)] for y in myears],
    }

    # Seasonal and diurnal profiles, over whole complete years only: a part-year
    # contributes its winter but not its autumn, which tilts every average.
    whole = {y for y in by_year if len(by_year[y]) >= 330}
    whole_hourly = {d: v for d, v in hourly.items() if int(d[:4]) in whole}
    season_acc = defaultdict(list)
    for d in days:
        if int(d[:4]) in whole:
            season_acc[int(d[4:6])].append(daily[d]["mean"])
    season = [round(sum(season_acc[m]) / len(season_acc[m]), 1) if season_acc[m] else None
              for m in range(1, 13)]

    # The last three days of hourly readings, for the live trace. Built as one
    # flat run of (label, value, is_midnight) and then trimmed, so the axis marks
    # are found in the window that is actually drawn rather than re-indexed into
    # it afterwards.
    MAB = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    run = []
    for d in days[-4:]:
        day_label = f"{int(d[6:8])} {MAB[int(d[4:6]) - 1]}"
        for h, v in enumerate(hourly.get(d, [])):
            run.append((f"{day_label} {h:02d}:00", v, day_label if h == 0 else None))
    run = run[-84:]
    recent_t = [r[0] for r in run]
    recent_v = [r[1] for r in run]
    marks = [{"i": i, "l": r[2]} for i, r in enumerate(run) if r[2]]

    live_block = None
    if live:
        vals24 = [s["pm25_24h"] for s in live if s.get("pm25_24h") is not None]
        vals1 = [s["pm25"] for s in live if s.get("pm25") is not None]
        t = live[0].get("time") if live else None
        if t:
            try:
                t = datetime.fromisoformat(t).strftime("%-d %b, %H:%M")
            except ValueError:
                pass
        live_block = {
            "city": round(sum(vals24) / len(vals24), 1) if vals24 else None,
            "hour": round(sum(vals1) / len(vals1), 1) if vals1 else None,
            "n": len(vals24 or vals1),
            "time": t,
            "stations": [dict(s, en=_en(s.get("name"))) for s in live],
        }

    return {
        "scales": aqi.js_payload(),
        "annual": annual,
        "byYear": by_year_days,
        "monthly": monthly,
        "season": season,
        "diurnal": {"all": pm25.diurnal(whole_hourly or hourly),
                    "rel": pm25.diurnal_relative(whole_hourly or hourly)},
        "allDaily": [daily[d]["mean"] for d in days],
        "recent": {"t": recent_t, "v": recent_v, "marks": marks},
        "live": live_block,
        "source": source_html,
        "mapNote": map_note,
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
        "curYear": cur_year,
    }
