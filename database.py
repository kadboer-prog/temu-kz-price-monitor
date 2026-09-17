from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_FILE = ROOT / "data" / "products.json"
PRICES_FILE = ROOT / "data" / "prices.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def load_products() -> list[dict[str, Any]]:
    data = load_json(PRODUCTS_FILE, [])
    return data if isinstance(data, list) else []


def load_prices() -> dict[str, Any]:
    data = load_json(PRICES_FILE, {})
    return data if isinstance(data, dict) else {}


def save_prices(data: dict[str, Any]) -> None:
    PRICES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRICES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def record_price(
    history: dict[str, Any],
    product_id: str,
    variant_key: str,
    price_kzt: int,
    checked_at: str,
) -> bool:
    key = f"{product_id}|{variant_key}"
    item = history.setdefault(
        key,
        {
            "product_id": product_id,
            "variant_key": variant_key,
            "prices": [],
        },
    )
    prices = item.setdefault("prices", [])

    if prices and prices[-1].get("price_kzt") == price_kzt:
        # Keep the history compact: do not append identical consecutive prices.
        return False

    prices.append({"checked_at": checked_at, "price_kzt": price_kzt})
    return True
