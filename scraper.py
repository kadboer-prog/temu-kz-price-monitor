from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from database import load_prices, load_products, record_price, save_prices
from temu import find_kzt_price, select_variant


def almaty_now_iso() -> str:
    # GitHub runners are UTC. Asia/Almaty is UTC+5.
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat(timespec="seconds")


async def check_product(page, product: dict, history: dict) -> int:
    url = product.get("url")
    product_id = str(product.get("id") or "")
    if not url or not product_id:
        return 0

    changed = 0
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)
    except PlaywrightTimeoutError:
        print(f"TIMEOUT loading {url}")
        return 0
    except Exception as exc:
        print(f"LOAD ERROR {url}: {exc}")
        return 0

    variants = product.get("variants") or []
    if not variants:
        result = await find_kzt_price(page)
        if result:
            if record_price(history, product_id, "default", result.price_kzt, almaty_now_iso()):
                changed += 1
                print(f"{product_id} default = {result.price_kzt} ₸")
        else:
            print(f"SKIP non-KZT/no price: {url}")
        return changed

    for variant in variants:
        key = str(variant.get("key") or " / ".join(variant.get("options") or []) or "default")
        options = variant.get("options") or []
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1800)
            selected = await select_variant(page, options)
            if not selected:
                print(f"Variant selection incomplete: {product_id} {key}")
            result = await find_kzt_price(page)
            if result:
                if record_price(history, product_id, key, result.price_kzt, almaty_now_iso()):
                    changed += 1
                    print(f"{product_id} {key} = {result.price_kzt} ₸")
            else:
                print(f"SKIP non-KZT/no price: {product_id} {key}")
        except Exception as exc:
            print(f"VARIANT ERROR {product_id} {key}: {exc}")

    return changed


async def main() -> None:
    products = load_products()
    history = load_prices()
    if not products:
        print("No tracked products in data/products.json")
        return

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="kk-KZ",
            timezone_id="Asia/Almaty",
            extra_http_headers={
                "Accept-Language": "kk-KZ,kk;q=0.9,en;q=0.8",
            },
        )
        page = await context.new_page()
        total_changed = 0
        for product in products:
            total_changed += await check_product(page, product, history)
        await context.close()
        await browser.close()

    save_prices(history)
    print(f"Completed. New history points: {total_changed}")


if __name__ == "__main__":
    asyncio.run(main())
