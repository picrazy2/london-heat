"""Shared HTTP helpers.

Every source here is keyless, which is the constraint that keeps the daily
GitHub Action free of secrets. What they are not is uniformly reliable, so
`get` retries and every caller is expected to survive a source being down —
a refresh that loses one day of one series must still publish the rest.
"""
import gzip
import io
import time
import urllib.error
import urllib.request

UA = "weather.akguo.com (+https://github.com/picrazy2/weather)"


def get(url, timeout=120, tries=3, headers=None, gunzip=False):
    """Fetch bytes, retrying on transient failures. Raises after the last try."""
    h = {"User-Agent": UA, "Accept-Encoding": "gzip"}
    if headers:
        h.update(headers)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or (gunzip and data[:2] == b"\x1f\x8b"):
                    data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
                return data
        except Exception as e:                      # noqa: BLE001 - retry anything
            last = e
            if i < tries - 1:
                time.sleep(1.5 * (i + 1))
    raise last


def get_text(url, encoding="utf-8", **kw):
    return get(url, **kw).decode(encoding, "replace")


def maybe(url, **kw):
    """Fetch, or return None if the source is unavailable. For optional days."""
    try:
        return get(url, **kw)
    except Exception:                                # noqa: BLE001
        return None
