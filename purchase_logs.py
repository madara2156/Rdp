"""Purchase log notifications for the configured Telegram log group.

The log intentionally contains order metadata only.  Purchased credentials,
phone numbers, OTPs and session data must never be copied into a group log.
"""

import html
import logging
from datetime import datetime

import database as db

logger = logging.getLogger(__name__)


def get_log_chat_id():
    """Return the configured Telegram log group ID, or an empty string."""
    return str(db.get_setting("purchase_log_chat_id", "") or "").strip()


def _buyer_label(user_id):
    user = db.get_user(user_id) or {}
    username = str(user.get("username") or "").strip()
    if username:
        return f"@{html.escape(username)}"
    full_name = str(user.get("full_name") or "").strip()
    if full_name:
        return html.escape(full_name)
    return f"User <code>{html.escape(str(user_id))}</code>"


def _money(amount_usdt):
    try:
        return f"{float(amount_usdt):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(amount_usdt or "0")


async def notify_purchase(
    bot,
    user_id,
    product_name,
    amount_usdt,
    *,
    order_id=None,
    purchase_type="Store purchase",
    quantity=1,
    details="",
):
    """Send one safe purchase notification to the configured log group.

    Returns True when a message was sent and False when logging is disabled or
    Telegram rejected the message.  A log failure must never break delivery.
    """
    raw_chat_id = get_log_chat_id()
    if not raw_chat_id:
        return False

    try:
        chat_id = int(raw_chat_id)
    except ValueError:
        logger.warning("Invalid purchase_log_chat_id: %r", raw_chat_id)
        return False

    lines = [
        "🛒 <b>New Purchase</b>",
        "",
        f"📦 <b>Product:</b> {html.escape(str(product_name or 'Unknown'))}",
        f"🏷️ <b>Type:</b> {html.escape(str(purchase_type or 'Store purchase'))}",
        f"🔢 <b>Quantity:</b> <code>{html.escape(str(quantity or 1))}</code>",
        f"💰 <b>Amount:</b> <code>{_money(amount_usdt)} USDT</code>",
        f"👤 <b>Buyer:</b> {_buyer_label(user_id)}",
        f"🆔 <b>User ID:</b> <code>{html.escape(str(user_id))}</code>",
    ]
    if order_id is not None:
        lines.append(f"🧾 <b>Order ID:</b> <code>{html.escape(str(order_id))}</code>")
    if details:
        lines.append(f"ℹ️ <b>Details:</b> {html.escape(str(details))}")
    lines.append(f"🕒 <code>{html.escape(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</code>")

    try:
        await bot.send_message(
            chat_id=chat_id,
            text="\n".join(lines),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception:
        logger.exception("Could not send purchase log to chat %s", chat_id)
        return False


def stock_added_message(
    product,
    added_count,
    total_stock,
    *,
    kind="Store stock",
    price_label=None,
):
    """Build a safe stock-added message for DMs and the log group."""
    product = product or {}
    emoji = str(product.get("emoji") or "📦")
    emoji_id = str(product.get("emoji_id") or "").strip()
    if emoji_id:
        emoji = (
            f'<tg-emoji emoji-id="{html.escape(emoji_id)}">'
            f"{html.escape(emoji)}</tg-emoji>"
        )
    else:
        emoji = html.escape(emoji)

    if price_label is None:
        try:
            price_label = f"{float(product.get('price_usdt') or 0):.2f} USDT"
        except (TypeError, ValueError):
            price_label = "See shop"

    return (
        "📦 <b>Stock Added</b>\n\n"
        f"{emoji} <b>{html.escape(str(product.get('name') or 'Stock'))}</b>\n"
        f"🏷️ <b>Type:</b> {html.escape(str(kind))}\n"
        f"➕ <b>New stock:</b> <code>{int(added_count or 0)}</code>\n"
        f"📊 <b>Available now:</b> <code>{int(total_stock or 0)}</code>\n"
        f"💵 <b>Price:</b> <code>{html.escape(str(price_label))}</code>\n\n"
        "<i>Fresh stock is now available for purchase.</i>"
    )


async def notify_stock_added(
    bot,
    product,
    added_count,
    total_stock,
    *,
    kind="Store stock",
    price_label=None,
):
    """Send a stock-added event to the configured log group only."""
    raw_chat_id = get_log_chat_id()
    if not raw_chat_id:
        return False
    try:
        chat_id = int(raw_chat_id)
    except ValueError:
        logger.warning("Invalid purchase_log_chat_id: %r", raw_chat_id)
        return False

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=stock_added_message(
                product,
                added_count,
                total_stock,
                kind=kind,
                price_label=price_label,
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception:
        logger.exception("Could not send stock log to chat %s", chat_id)
        return False