"""Small async/sync client for the ZapUPI REST API.

The Telegram bot uses the async helpers.  The Flask webhook uses the sync
helper because it runs outside the bot's asyncio event loop.
"""

import asyncio
import json
from typing import Any, Dict, Optional

import aiohttp
import requests

import config


def configured() -> bool:
    return bool(getattr(config, "ZAPUPI_API_KEY", ""))


def _status_payload(data: Any) -> Dict[str, Any]:
    """Normalize ZapUPI's top-level/data response shapes."""
    if not isinstance(data, dict):
        return {}
    nested = data.get("data")
    return nested if isinstance(nested, dict) else data


async def _post_async(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not configured():
        return {"status": "error", "message": "ZapUPI is not configured"}
    url = f"{config.ZAPUPI_API_BASE}/{endpoint.lstrip('/')}"
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                raw = await response.text()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    return {"status": "error", "message": f"Invalid ZapUPI response ({response.status})"}
                if not isinstance(data, dict):
                    return {"status": "error", "message": "Invalid ZapUPI response"}
                return data
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
        return {"status": "error", "message": str(exc) or "ZapUPI connection failed"}


async def create_order(
    order_id: str,
    amount_inr: float,
    remark: str = "",
    customer_mobile: str = "",
    webhook_url: str = "",
) -> Dict[str, Any]:
    payload = {
        "zap_key": config.ZAPUPI_API_KEY,
        "order_id": order_id,
        "amount": f"{amount_inr:.2f}",
    }
    if remark:
        payload["remark"] = remark
    if customer_mobile:
        payload["customer_mobile"] = customer_mobile
    if webhook_url:
        payload["webhook_url"] = webhook_url
    return await _post_async("create-order", payload)


async def order_status(order_id: str) -> Dict[str, Any]:
    return await _post_async(
        "order-status",
        {"zap_key": config.ZAPUPI_API_KEY, "order_id": order_id},
    )


def order_status_sync(order_id: str) -> Dict[str, Any]:
    """Server-side status confirmation for the Flask webhook."""
    if not configured():
        return {"status": "error", "message": "ZapUPI is not configured"}
    url = f"{config.ZAPUPI_API_BASE}/order-status"
    try:
        response = requests.post(
            url,
            json={"zap_key": config.ZAPUPI_API_KEY, "order_id": order_id},
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        data = response.json()
        return data if isinstance(data, dict) else {"status": "error", "message": "Invalid ZapUPI response"}
    except (requests.RequestException, ValueError, OSError) as exc:
        return {"status": "error", "message": str(exc) or "ZapUPI connection failed"}


def response_data(response: Dict[str, Any]) -> Dict[str, Any]:
    return _status_payload(response)


def response_ok(response: Dict[str, Any]) -> bool:
    return str(response.get("status", "")).lower() == "success"


def payment_url(response: Dict[str, Any]) -> str:
    return str(response.get("payment_url") or response_data(response).get("payment_url") or "").strip()


def payment_status(response: Dict[str, Any]) -> str:
    value = response_data(response).get("status", response.get("payment_status", ""))
    return str(value or "").strip().lower()


def amount(response: Dict[str, Any]) -> Optional[float]:
    value = response_data(response).get("pay_amount")
    if value in (None, ""):
        value = response_data(response).get("amount")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def txn_id(response: Dict[str, Any]) -> str:
    data = response_data(response)
    return str(data.get("txn_id") or "").strip()


def utr(response: Dict[str, Any]) -> str:
    data = response_data(response)
    return str(data.get("utr") or "").strip()


def environment(response: Dict[str, Any]) -> str:
    data = response_data(response)
    return str(data.get("environment") or "").strip().lower()