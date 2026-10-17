"""Exchange rates: the one place that knows where they come from (open.er-api.com, free, no key).

It imports almost nothing, so the currency-converter window opens instantly. The convert_currency
tool and that window both use it, which is why the two always agree.
"""
import time

import requests

URL = "https://open.er-api.com/v6/latest/{base}"
CACHE_SECONDS = 3600
_cache = {}


class RateError(Exception):
    """Rates could not be fetched; the message is fit to show or read aloud."""


def rates(base):
    """{code: rate} for one unit of ``base``, cached for an hour."""
    base = (base or "").strip().upper()
    if not (len(base) == 3 and base.isalpha()):
        raise RateError(f"{base or 'That'} is not a currency code.")
    cached = _cache.get(base)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        response = requests.get(URL.format(base=base), timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.Timeout:
        raise RateError("open.er-api.com took too long to answer.") from None
    except requests.ConnectionError:
        raise RateError("I couldn't reach open.er-api.com. Check the internet connection.") from None
    except (requests.RequestException, ValueError):
        raise RateError("open.er-api.com sent something I couldn't read.") from None
    if data.get("result") != "success" or not isinstance(data.get("rates"), dict):
        raise RateError(f"I couldn't get exchange rates for {base}.")
    _cache[base] = (time.time(), data["rates"])
    return data["rates"]


def convert(amount, source, target):
    """``amount`` of ``source`` currency expressed in ``target`` currency."""
    rate = rates(source).get((target or "").strip().upper())
    if rate is None:
        raise RateError(f"I couldn't get a rate from {source.strip().upper()} to {(target or '').strip().upper()}.")
    return amount * rate


def codes(base="USD"):
    """Every currency code the service knows, sorted."""
    return sorted(rates(base))
