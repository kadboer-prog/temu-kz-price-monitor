from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from playwright.async_api import Page


@dataclass
class PriceResult:
    price_kzt: int
    raw_text: str


KZT_RE = re.compile(r"(?:₸|KZT)\s*([0-9][0-9\s.,]*)|([0-9][0-9\s.,]*)\s*(?:₸|KZT)", re.I)


def _normalize_number(text: str) -> int | None:
    s = text.replace("\u00a0", " ").strip()
    s = re.sub(r"[^0-9,\.\s]", "", s)
    if not re.search(r"\d", s):
        return None
    # Prices in KZT are normally displayed as an integer amount. Handle both
    # thousands-space and decimal punctuation conservatively.
    s = s.replace(" ", "")
    if s.count(",") == 1 and s.count(".") == 0 and len(s.split(",")[-1]) in (1, 2):
        s = s.split(",")[0]
    elif s.count(".") == 1 and s.count(",") == 0 and len(s.split(".")[-1]) in (1, 2):
        s = s.split(".")[0]
    else:
        s = s.replace(",", "").replace(".", "")
    try:
        return int(s)
    except ValueError:
        return None


async def find_kzt_price(page: Page) -> PriceResult | None:
    # Prefer visible text: it reflects the price the shopper currently sees.
    body = await page.locator("body").inner_text(timeout=15000)
    matches = list(KZT_RE.finditer(body))
    candidates: list[tuple[int, str]] = []
    for m in matches:
        raw = m.group(1) or m.group(2)
        value = _normalize_number(raw)
        if value is not None and value > 0:
            candidates.append((value, m.group(0)))

    if not candidates:
        return None

    # The first matching KZT amount around the product area is generally the
    # current selling price. Keep the smallest positive candidate as a fallback
    # because Temu often shows both sale and original prices.
    candidates.sort(key=lambda x: x[0])
    return PriceResult(price_kzt=candidates[0][0], raw_text=candidates[0][1])


async def visible_option_labels(page: Page) -> list[str]:
    # Generic extraction. Temu changes CSS frequently, so avoid brittle class names.
    labels = await page.locator("button, [role='button']").all_inner_texts()
    out: list[str] = []
    for text in labels:
        t = " ".join(text.split())
        if 1 <= len(t) <= 80 and t not in out:
            out.append(t)
    return out


async def select_option_by_text(page: Page, option_text: str) -> bool:
    target = " ".join(option_text.split())
    candidates = page.get_by_text(target, exact=True)
    count = await candidates.count()
    for i in range(min(count, 8)):
        el = candidates.nth(i)
        try:
            if await el.is_visible():
                await el.click(timeout=4000)
                await page.wait_for_timeout(700)
                return True
        except Exception:
            continue
    return False


async def select_variant(page: Page, options: Iterable[str]) -> bool:
    ok = True
    for option in options:
        ok = await select_option_by_text(page, option) and ok
    return ok
