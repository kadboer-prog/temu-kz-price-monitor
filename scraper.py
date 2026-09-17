from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from database import load_prices, load_products, record_price, save_prices
from temu import capture_network_price, find_kzt_price, inspect_page, select_variant

def almaty_now_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat(timespec="seconds")

async def check_product(page, product: dict, history: dict) -> int:
    url = product.get("url")
    product_id = str(product.get("id") or "")
    if not url or not product_id:
        print("SKIP invalid product entry")
        return 0

    network_results = []
    async def on_response(response):
        result = await capture_network_price(response)
        if result:
            network_results.append(result)
            print(f"NETWORK PRICE: {result.price_kzt} ₸ ({result.raw_text})")

    page.on("response", on_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        info = await inspect_page(page)
        print(f"PAGE URL: {info['url']}")
        print(f"PAGE TITLE: {info['title']}")
        print(f"KZT symbol: {info['has_kzt_symbol']}, KZT text: {info['has_kzt_word']}")
        if info["looks_like_login"]:
            print("WARNING: page looks like a login/registration page.")
        print(f"BODY EXCERPT: {info['body_excerpt']!r}")

        variants = product.get("variants") or []
        if not variants:
            result = await find_kzt_price(page, network_results)
            if result:
                if record_price(history, product_id, "default", result.price_kzt, almaty_now_iso()):
                    print(f"SAVED {product_id} default = {result.price_kzt} ₸ [{result.source}]")
                    return 1
                print(f"NO CHANGE {product_id} default = {result.price_kzt} ₸ [{result.source}]")
                return 0

            await page.screenshot(path="debug-no-price.png", full_page=True)
            with open("debug-no-price.html", "w", encoding="utf-8") as f:
                f.write(await page.content())
            print("NO KZT PRICE FOUND. Debug screenshot/HTML created.")
            return 0

        changed = 0
        for variant in variants:
            key = str(variant.get("key") or " / ".join(variant.get("options") or []) or "default")
            options = variant.get("options") or []

            network_results.clear()
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3500)

            selected = await select_variant(page, options)
            print(f"VARIANT {key}: selected={selected}")
            await page.wait_for_timeout(2000)

            result = await find_kzt_price(page, network_results)
            if result:
                if record_price(history, product_id, key, result.price_kzt, almaty_now_iso()):
                    changed += 1
                    print(f"SAVED {product_id} {key} = {result.price_kzt} ₸ [{result.source}]")
                else:
                    print(f"NO CHANGE {product_id} {key} = {result.price_kzt} ₸ [{result.source}]")
            else:
                print(f"NO KZT PRICE FOUND: {product_id} {key}")

        return changed
    except PlaywrightTimeoutError:
        print(f"TIMEOUT loading {url}")
        return 0
    except Exception as exc:
        print(f"LOAD ERROR {url}: {type(exc).__name__}: {exc}")
        return 0
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

async def main() -> None:
    products = load_products()
    history = load_prices()

    print(f"Tracked products: {len(products)}")
    if not products:
        print("No tracked products in products.json")
        return

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            locale="kk-KZ",
            timezone_id="Asia/Almaty",
            viewport={"width": 1440, "height": 1000},
            extra_http_headers={
                "Accept-Language": "kk-KZ,ru-KZ,ru;q=0.9,en;q=0.8",
            },
        )
        page = await context.new_page()
        changed = 0

        for product in products:
            print("=" * 80)
            print(f"CHECKING: {product.get('id')} {product.get('url')}")
            changed += await check_product(page, product, history)

        await context.close()
        await browser.close()

    save_prices(history)
    print(f"Completed. New history points: {changed}")

if __name__ == "__main__":
    asyncio.run(main())
