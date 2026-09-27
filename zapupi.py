"""Small async/sync client for the ZapUPI REST API.

The Telegram bot uses the async helpers.  The Flask webhook uses the sync
helper because it runs outside the bot's asyncio event loop.
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import aiohttp
import requests

import config

logger = logging.getLogger(__name__)


def configured() -> bool:
    return bool(str(getattr(config, "ZAPUPI_API_KEY", "") or "").strip())


def _status_payload(data: Any) -> Dict[str, Any]:
    """Return the provider's useful order object.

    The documented ``order-status`` response is ``{"status": "success",
    "data": {...}}`` while webhook payloads are flat.  A few gateway
    deployments have additionally wrapped the same object in ``result`` or
    ``order``.  Walk those wrappers without mutating the original response.
    """
    current = data
    seen = set()
    while isinstance(current, dict):
        marker = id(current)
        if marker in seen:
            break
        seen.add(marker)
        for key in ("data", "result", "order"):
            nested = current.get(key)
            if isinstance(nested, dict) and nested is not current:
                current = nested
                break
        else:
            return current
    return current if isinstance(current, dict) else {}


def _first_value(response: Dict[str, Any], *keys: str) -> Any:
    """Read a field from the nested payload and then the top-level response."""
    data = response_data(response)
    for source in (data, response):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return None


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
                    return {
                        "status": "error",
                        "message": f"Invalid ZapUPI response ({response.status})",
                        "_http_status": response.status,
                    }
                if not isinstance(data, dict):
                    return {
                        "status": "error",
                        "message": "Invalid ZapUPI response",
                        "_http_status": response.status,
                    }
                # Keep transport status separate from the provider's JSON
                # status.  This prevents a malformed/non-2xx response from
                # ever being accepted as a successful order.
                data.setdefault("_http_status", response.status)
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
        if not isinstance(data, dict):
            return {
                "status": "error",
                "message": "Invalid ZapUPI response",
                "_http_status": response.status_code,
            }
        data.setdefault("_http_status", response.status_code)
        return data
    except (requests.RequestException, ValueError, OSError) as exc:
        return {"status": "error", "message": str(exc) or "ZapUPI connection failed"}


def response_data(response: Dict[str, Any]) -> Dict[str, Any]:
    return _status_payload(response)


def response_ok(response: Dict[str, Any]) -> bool:
    """Return whether ZapUPI accepted the API request.

    ZapUPI has used both ``status: success`` and ``success: true`` in
    different API responses.  Keep this check limited to the transport/API
    result; the actual payment result is checked separately by
    :func:`payment_status`.
    """
    if not isinstance(response, dict):
        return False
    try:
        http_status = int(response.get("_http_status", 200))
    except (TypeError, ValueError):
        return False
    if not 200 <= http_status < 300:
        return False
    if response.get("success") is True or str(response.get("success", "")).strip().lower() == "true":
        return True

    # The create-order endpoint uses ``success`` while a few order-status
    # responses expose the paid state directly.  The caller separately checks
    # payment_status before crediting.
    status = str(
        response.get("status")
        or response_data(response).get("status")
        or ""
    ).strip().lower()
    return status in {"success", "ok", "created", "paid", "completed"}


def error_message(response: Dict[str, Any]) -> str:
    """Return a short provider error for server logs without exposing secrets."""
    if not isinstance(response, dict):
        return "invalid response"
    value = (
        response.get("message")
        or response.get("error")
        or response_data(response).get("message")
        or response_data(response).get("error")
        or "unknown provider error"
    )
    return str(value).replace("\n", " ").strip()[:300]


def payment_url(response: Dict[str, Any]) -> str:
    value = _first_value(response, "payment_url", "payment_link", "paymentLink", "url")
    return str(value or "").strip()


def payment_status(response: Dict[str, Any]) -> str:
    value = _first_value(
        response,
        "payment_status", "paymentStatus", "order_status", "orderStatus",
        "payment_state", "paymentState", "state", "status",
    )
    return str(value or "").strip().lower()


def amount(response: Dict[str, Any]) -> Optional[float]:
    value = _first_value(
        response,
        # ``amount`` and ``pay_amount`` are the documented fields.  The
        # remaining aliases keep status responses from older gateway versions
        # readable without changing the crediting rules.
        "pay_amount", "payAmount", "paid_amount", "paidAmount", "amount",
        "amount_inr", "amountInr", "order_amount", "orderAmount",
        "total_amount", "totalAmount",
    )
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def txn_id(response: Dict[str, Any]) -> str:
    value = _first_value(
        response,
        "txn_id", "txnId", "transaction_id", "transactionId",
        "provider_txn_id", "providerTxnId",
    )
    return str(value or "").strip()


def utr(response: Dict[str, Any]) -> str:
    value = _first_value(
        response,
        "utr", "utr_number", "utrNumber", "bank_reference", "bankReference",
        "bank_ref", "bankRef",
    )
    return str(value or "").strip()


def environment(response: Dict[str, Any]) -> str:
    value = _first_value(response, "environment", "env")
    return str(value or "").strip().lower()


def order_id(response: Dict[str, Any]) -> str:
    """Return the provider's canonical order id from a create/status response."""
    value = _first_value(
        response,
        "order_id", "orderId", "merchant_order_id", "merchantOrderId",
        "client_order_id", "clientOrderId",
    )
    return str(value or "").strip()