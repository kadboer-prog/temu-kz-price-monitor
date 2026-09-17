from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from playwright.async_api import Page

@dataclass
class PriceResult:
    price_kzt: int
    raw_text: str
    source: str

KZT_RE = re.compile(
    r"(?:₸|KZT|тңг|теңге)\s*([0-9][0-9\s.,]*)|"
    r"([0-9][0-9\s.,]*)\s*(?:₸|KZT|тңг|теңге)",
    re.IGNORECASE,
)

PRICE_KEYS = ("price_str", "price_schema", "price_text", "price")

def _normalize_number(text: str) -> int | None:
    s = text.replace("\u00a0", " ").strip()
    s = re.sub(r"[^\d,.\s]", "", s)
    if not re.search(r"\d", s):
        return None
    s = re.sub(r"\s+", "", s)

    # KZT is normally an integer. For decimal-looking values, drop the
    # fractional part conservatively.
    if "," in s and "." not in s:
        left, right = s.rsplit(",", 1)
        if len(right) in (1, 2):
            s = left
        else:
            s = s.replace(",", "")
    elif "." in s and "," not in s:
        left, right = s.rsplit(".", 1)
        if len(right) in (1, 2):
            s = left
        else:
            s = s.replace(".", "")
    else:
        s = s.replace(",", "").replace(".", "")

    try:
        value = int(s)
    except ValueError:
        return None
    return value if value > 0 else None

def _price_from_text(text: str) -> int | None:
    m = KZT_RE.search(text)
    if not m:
        return None
    return _normalize_number(m.group(1) or m.group(2))

def _price_from_jsonld(data: Any) -> PriceResult | None:
    if isinstance(data, dict):
        offers = data.get("offers")
        if isinstance(offers, dict):
            currency = str(offers.get("priceCurrency") or "").upper()
            if currency == "KZT":
                value = _normalize_number(str(offers.get("price") or ""))
                if value:
                    return PriceResult(value, f"{value} KZT", "json-ld")
        for value in data.values():
            result = _price_from_jsonld(value)
            if result:
                return result
    elif isinstance(data, list):
        for value in data:
            result = _price_from_jsonld(value)
            if result:
                return result
    return None

def _price_from_api_json(data: Any) -> PriceResult | None:
    """
    Search Temu's JSON responses for a price object where the currency and
    price are siblings. Public examples of Temu data expose fields such as
    currency, price_str and price_schema. This avoids guessing a numeric
    value from unrelated JSON fields.
    """
    if isinstance(data, dict):
        currency = str(data.get("currency") or data.get("price_currency") or "").upper()
        if currency == "KZT":
            # Prefer the site's already-formatted value.
            for key in ("price_str", "price_schema"):
                value = data.get(key)
                if value is not None:
                    parsed = _price_from_text(str(value))
                    if parsed is None:
                        parsed = _normalize_number(str(value))
                    if parsed:
                        return PriceResult(parsed, str(value), "network-json")
            pt = data.get("price_text")
            if isinstance(pt, list):
                parsed = _price_from_text(" ".join(map(str, pt)))
                if parsed:
                    return PriceResult(parsed, " ".join(map(str, pt)), "network-json")
            if data.get("price") is not None:
                parsed = _normalize_number(str(data["price"]))
                # Temu examples use minor units for USD; do not trust a bare
                # KZT integer unless it looks like a plausible tenge price.
                if parsed and parsed >= 100:
                    return PriceResult(parsed, str(data["price"]), "network-json")
        for value in data.values():
            result = _price_from_api_json(value)
            if result:
                return result
    elif isinstance(data, list):
        for value in data:
            result = _price_from_api_json(value)
            if result:
                return result
    return None

async def find_kzt_price(
    page: Page,
    network_results: list[PriceResult] | None = None,
) -> PriceResult | None:
    # 1) Network JSON captured after the page's JS executed.
    if network_results:
        for result in network_results:
            if result.price_kzt > 0:
                return result

    # 2) JSON-LD structured data.
    scripts = page.locator('script[type="application/ld+json"]')
    try:
        for i in range(await scripts.count()):
            raw = await scripts.nth(i).text_content()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            result = _price_from_jsonld(data)
            if result:
                return result
    except Exception:
        pass

    # 3) Visible rendered page text.
    try:
        body = await page.locator("body").inner_text(timeout=15000)
    except Exception:
        body = ""

    # Take the first plausible KZT price in the rendered page.
    candidates: list[int] = []
    for m in KZT_RE.finditer(body):
        value = _normalize_number(m.group(1) or m.group(2))
        if value:
            candidates.append(value)

    if candidates:
        # Prefer the smallest plausible selling price when both sale and
        # original/list prices are visible.
        return PriceResult(min(candidates), f"{min(candidates)} ₸", "dom")

    return None

async def inspect_page(page: Page) -> dict[str, Any]:
    try:
        body = await page.locator("body").inner_text(timeout=8000)
    except Exception:
        body = ""
    return {
        "url": page.url,
        "title": await page.title(),
        "has_kzt_symbol": "₸" in body,
        "has_kzt_word": "KZT" in body.upper() or "теңге" in body.lower(),
        "looks_like_login": any(
            marker in body.lower()
            for marker in ("кіру", "тіркелу", "войти", "зарегистр", "log in", "sign in")
        ),
        "body_excerpt": body[:1200],
    }

async def select_option_by_text(page: Page, option_text: str) -> bool:
    target = " ".join(option_text.split())
    if not target:
        return True
    candidates = page.get_by_text(target, exact=True)
    count = await candidates.count()
    for i in range(min(count, 8)):
        el = candidates.nth(i)
        try:
            if await el.is_visible():
                await el.click(timeout=4000)
                await page.wait_for_timeout(900)
                return True
        except Exception:
            continue
    return False

async def select_variant(page: Page, options: Iterable[str]) -> bool:
    ok = True
    for option in options:
        ok = await select_option_by_text(page, option) and ok
    return ok

async def capture_network_price(response) -> PriceResult | None:
    try:
        if response.status < 200 or response.status >= 300:
            return None
        url = response.url.lower()
        if "temu.com" not in url:
            return None

        ctype = (response.headers.get("content-type") or "").lower()
        if "json" not in ctype and "javascript" not in ctype:
            return None

        text = await response.text()
        if len(text) > 5_000_000:
            return None

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        return _price_from_api_json(data)
    except Exception:
        return None
