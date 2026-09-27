"""MongoDB replacement for the legacy SQLite database API.

The bot historically imported ``database`` directly.  This module deliberately
keeps that API and the old dictionary field names, while storing every runtime
record in MongoDB.  IDs are numeric and are allocated by ``mongo_client`` so
existing callback data and admin URLs remain compatible.
"""

import random
import string
from datetime import datetime, timedelta

import config
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from mongo_client import col, next_id, now_iso, ensure_indexes, strip_id, strip_ids


def _clean(value):
    return strip_id(value) if value else None


def _docs(cursor):
    return strip_ids(list(cursor))


def _gen_ref():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def _new(name, **fields):
    fields.setdefault("id", next_id(name))
    return fields


def _user(uid):
    return col("users").find_one({"user_id": int(uid)})


def init_db():
    """Initialize indexes and the default category.

    No local database or filesystem is touched.  Existing SQLite data is not
    silently imported because doing so on every Render boot would duplicate
    records; use the one-time migration tool if old data must be retained.
    """
    ensure_indexes()
    if not col("categories").find_one({"name": "General"}):
        add_category("General", "🛍️")


def get_conn():
    raise RuntimeError(
        "SQLite get_conn() is unavailable: this deployment uses MongoDB. "
        "Replace direct SQL callers with database API methods."
    )


# ── users / wallet ───────────────────────────────────────────────────────────
def get_or_create_user(user_id: int, username: str = "", full_name: str = ""):
    uid = int(user_id)
    user = _user(uid)
    if user:
        patch = {}
        if username: patch["username"] = username
        if full_name: patch["full_name"] = full_name
        if patch:
            col("users").update_one({"user_id": uid}, {"$set": patch})
            user.update(patch)
        return _clean(user)
    code = _gen_ref()
    while col("users").find_one({"referral_code": code}):
        code = _gen_ref()
    doc = {
        "user_id": uid, "username": username or "", "full_name": full_name or "",
        "balance": 0.0, "referral_code": code, "referred_by": None,
        "total_orders": 0, "total_spent_usdt": 0.0, "is_vip": 0,
        "is_banned": 0, "language": "", "claimed_free_item": 0,
        "joined_at": now_iso(),
    }
    try:
        col("users").insert_one(doc)
    except DuplicateKeyError:
        pass
    return _clean(col("users").find_one({"user_id": uid}))


def get_user(user_id: int):
    return _clean(_user(user_id))


def user_exists(user_id: int) -> bool:
    return bool(_user(user_id))


def get_user_language(user_id: int) -> str:
    return (_user(user_id) or {}).get("language") or "en"


def set_user_language(user_id: int, lang: str):
    col("users").update_one({"user_id": int(user_id)}, {"$set": {"language": lang}},
                            upsert=False)


def update_balance(user_id: int, delta: float, reason="adjustment",
                   reference_type="", reference_id=None):
    uid, amount = int(user_id), float(delta)
    col("users").update_one({"user_id": uid},
                            {"$inc": {"balance": amount}})
    _wallet_log(uid, amount, "credit" if amount >= 0 else "debit",
                reason, reference_type, reference_id)
    return True


def debit_balance(user_id: int, amount: float, reason="purchase",
                  reference_type="", reference_id=None):
    amount = round(float(amount), 6)
    if amount < 0:
        raise ValueError("debit amount cannot be negative")
    result = col("users").update_one(
        {"user_id": int(user_id), "balance": {"$gte": amount}},
        {"$inc": {"balance": -amount}},
    )
    if result.modified_count:
        _wallet_log(user_id, -amount, "debit", reason, reference_type, reference_id)
        return True
    return False


def _wallet_log(user_id, amount, kind, reason, reference_type="", reference_id=None):
    col("wallet_transactions").insert_one(_new(
        "wallet_transactions", user_id=int(user_id), amount=float(amount),
        kind=kind, reason=reason, reference_type=reference_type,
        reference_id=reference_id, created_at=now_iso()))


def get_all_users():
    return _docs(col("users").find().sort("joined_at", DESCENDING))


def ban_user(user_id: int, ban: bool):
    col("users").update_one({"user_id": int(user_id)},
                            {"$set": {"is_banned": 1 if ban else 0}})


def search_users(query: str):
    q = str(query)
    return _docs(col("users").find({"$or": [
        {"user_id": {"$regex": q}},
        {"username": {"$regex": q, "$options": "i"}},
        {"full_name": {"$regex": q, "$options": "i"}},
    ]}).limit(20))


# ── categories / products ────────────────────────────────────────────────────
def get_categories(active_only=True):
    match = {"is_active": 1} if active_only else {}
    return _docs(col("categories").find(match).sort("id", ASCENDING))


def add_category(name, emoji):
    cid = next_id("categories")
    col("categories").insert_one({"id": cid, "name": name, "emoji": emoji,
                                  "is_active": 1})
    return cid


def toggle_category(cid):
    row = col("categories").find_one({"id": int(cid)})
    if not row: return None
    val = 0 if row.get("is_active", 1) else 1
    col("categories").update_one({"id": int(cid)}, {"$set": {"is_active": val}})
    return val


def delete_category(cid, force=False):
    cid = int(cid)
    if col("products").find_one({"category_id": cid}) and not force:
        return False
    if force:
        general = col("categories").find_one({"name": "General", "id": {"$ne": cid}})
        if not general:
            gid = add_category("General", "🛍️")
        else:
            gid = general["id"]
        col("products").update_many({"category_id": cid}, {"$set": {"category_id": gid}})
    col("categories").delete_one({"id": cid})
    return True


def get_category(cid):
    return _clean(col("categories").find_one({"id": int(cid)}))


def get_products(category_id=None, active_only=True):
    match = {}
    if category_id: match["category_id"] = int(category_id)
    if active_only: match["is_active"] = 1
    return _docs(col("products").find(match).sort("id", ASCENDING))


def get_product(pid):
    return _clean(col("products").find_one({"id": int(pid)}))


def add_product(category_id, name, emoji, description, price_usdt, duration, emoji_id=""):
    pid = next_id("products")
    col("products").insert_one({
        "id": pid, "category_id": int(category_id), "name": name, "emoji": emoji,
        "description": description, "price_usdt": float(price_usdt),
        "duration": duration, "stock_count": 0, "is_active": 1,
        "emoji_id": emoji_id or "", "low_stock_alert_sent": 0,
        "created_at": now_iso(),
    })
    return pid


def update_product_emoji_id(pid, emoji_id):
    col("products").update_one({"id": int(pid)}, {"$set": {"emoji_id": emoji_id}})


def delete_product(pid):
    col("products").delete_one({"id": int(pid)})


# ── normal shop stock ────────────────────────────────────────────────────────
def get_stock_count(product_id):
    return col("stock_items").count_documents(
        {"product_id": int(product_id), "is_sold": 0})


def refresh_stock_count(product_id):
    n = get_stock_count(product_id)
    col("products").update_one({"id": int(product_id)}, {"$set": {"stock_count": n}})
    return n


def refresh_stock_count_conn(_conn, product_id):
    """Legacy signature; Mongo does not use a per-request SQL connection."""
    return refresh_stock_count(product_id)


def add_stock(product_id, items: list):
    pid = int(product_id)
    existing = {x.get("data_norm") for x in col("stock_items").find(
        {"product_id": pid}, {"data_norm": 1})}
    added, duplicate_lines = [], []
    for item in items:
        raw, norm = str(item).strip(), str(item).strip().lower()
        if not raw: continue
        if norm in existing:
            duplicate_lines.append(raw)
        else:
            existing.add(norm); added.append(raw)
    for raw in added:
        col("stock_items").insert_one(_new(
            "stock_items", product_id=pid, data=raw, data_norm=raw.lower(),
            is_sold=0, sold_to=None, order_id=None, added_at=now_iso(), sold_at=None))
    refresh_stock_count(pid)
    return {"added": len(added), "duplicates": len(duplicate_lines),
            "duplicate_lines": duplicate_lines}


def pop_stock(product_id, qty=1):
    rows = []
    for _ in range(int(qty)):
        row = col("stock_items").find_one_and_update(
            {"product_id": int(product_id), "is_sold": 0},
            {"$set": {"is_sold": 1, "reserved_at": now_iso()}},
        )
        if not row: break
        rows.append(_clean(row))
    return rows


def mark_stock_sold(item_id, user_id, order_id):
    col("stock_items").update_one(
        {"id": int(item_id)},
        {"$set": {"is_sold": 1, "sold_to": int(user_id), "order_id": int(order_id),
                  "sold_at": now_iso()}})


def get_stock_items(product_id, include_sold=False, limit=50):
    match = {"product_id": int(product_id)}
    if not include_sold: match["is_sold"] = 0
    return _docs(col("stock_items").find(match).sort("id", ASCENDING).limit(int(limit)))


def edit_stock_item(item_id, new_data):
    r = col("stock_items").update_one(
        {"id": int(item_id), "is_sold": 0},
        {"$set": {"data": new_data, "data_norm": new_data.strip().lower()}})
    return bool(r.matched_count)


def remove_stock_item(item_id):
    row = col("stock_items").find_one({"id": int(item_id)})
    col("stock_items").delete_one({"id": int(item_id)})
    if row: refresh_stock_count(row["product_id"])


def clear_stock(product_id):
    col("stock_items").delete_many({"product_id": int(product_id), "is_sold": 0})
    refresh_stock_count(product_id)


# ── orders (normal and TG Store share this collection) ───────────────────────
def create_order(user_id, product_id, product_name, amount_usdt, stock_item_id=None,
                 coupon_code=None, is_reseller_sale=False, source="normal",
                 otp_order_id=None):
    oid = next_id("orders")
    doc = {
        "id": oid, "user_id": int(user_id), "product_id": int(product_id or 0),
        "product_name": product_name, "amount_usdt": float(amount_usdt),
        "status": "completed", "stock_item_id": stock_item_id,
        "coupon_code": coupon_code, "is_reseller_sale": 1 if is_reseller_sale else 0,
        "reminder_sent": 0, "refunded": 0, "source": source,
        "otp_order_id": otp_order_id, "created_at": now_iso(),
    }
    col("orders").insert_one(doc)
    col("users").update_one({"user_id": int(user_id)}, {
        "$inc": {"total_orders": 1, "total_spent_usdt": float(amount_usdt)}})
    if stock_item_id:
        mark_stock_sold(stock_item_id, user_id, oid)
    if product_id:
        refresh_stock_count(product_id)
    return oid


def _orders_with_user(match=None, limit=1000000, skip=0):
    rows = _docs(col("orders").find(match or {}).sort("id", DESCENDING)
                 .skip(int(skip)).limit(int(limit)))
    for row in rows:
        u = _user(row.get("user_id"))
        row["username"] = (u or {}).get("username", "")
        sid = row.get("stock_item_id")
        if sid:
            s = col("stock_items").find_one({"id": sid}, {"data": 1})
            row["cred_data"] = (s or {}).get("data")
    return rows


def get_user_orders(user_id, limit=20, offset=0):
    return _orders_with_user({"user_id": int(user_id)}, limit, offset)


def get_user_order_count(user_id):
    return col("orders").count_documents({"user_id": int(user_id)})


def get_order(oid):
    return _clean(col("orders").find_one({"id": int(oid)}))


def get_order_credential(oid):
    """Return a normal-shop credential attached to an order.

    TG Store orders have no stock_items credential; their account delivery is
    handled by otp_module instead.
    """
    order = col("orders").find_one({"id": int(oid)}, {"stock_item_id": 1})
    if not order:
        return None
    item = None
    if order.get("stock_item_id"):
        item = col("stock_items").find_one({"id": order["stock_item_id"]}, {"data": 1})
    if not item:
        item = col("stock_items").find_one({"order_id": int(oid)}, {"data": 1})
    return (item or {}).get("data")

def get_today_orders(limit=10000):
    prefix = datetime.now().strftime("%Y-%m-%d")
    return _orders_with_user({"created_at": {"$regex": "^" + prefix}}, limit)


def get_all_orders(limit=1000000):
    return _orders_with_user({}, limit)


def get_due_renewal_orders(cutoff):
    return _orders_with_user({
        "created_at": {"$lte": cutoff},
        "status": "completed",
        "reminder_sent": 0,
        "refunded": 0,
    }, limit=100000)


def mark_order_reminder_sent(oid):
    return col("orders").update_one(
        {"id": int(oid)}, {"$set": {"reminder_sent": 1}}
    ).modified_count > 0


def refund_order(oid):
    order = col("orders").find_one_and_update(
        {"id": int(oid), "refunded": {"$ne": 1}},
        {"$set": {"refunded": 1, "status": "refunded", "refunded_at": now_iso()}},
    )
    if not order: return None
    update_balance(order["user_id"], order["amount_usdt"], "refund", "order", oid)
    col("users").update_one({"user_id": order["user_id"]},
                            {"$inc": {"total_spent_usdt": -order["amount_usdt"]}})
    if order.get("stock_item_id"):
        col("stock_items").update_one({"id": order["stock_item_id"]}, {"$set": {
            "is_sold": 0, "sold_to": None, "order_id": None, "sold_at": None}})
        refresh_stock_count(order["product_id"])
    return _clean(order)


# ── free items ───────────────────────────────────────────────────────────────
def create_free_item(name, emoji, description=""):
    fid = next_id("free_items")
    col("free_items").insert_one({"id": fid, "name": name, "emoji": emoji,
        "description": description, "is_active": 1, "created_at": now_iso()})
    return fid


def get_free_items(active_only=True):
    return _docs(col("free_items").find({"is_active": 1} if active_only else {})
                 .sort("id", DESCENDING))


def get_free_item(fid):
    return _clean(col("free_items").find_one({"id": int(fid)}))


def toggle_free_item(fid):
    row = get_free_item(fid)
    if not row: return None
    val = 0 if row.get("is_active", 1) else 1
    col("free_items").update_one({"id": int(fid)}, {"$set": {"is_active": val}})
    return val


def delete_free_item(fid):
    col("free_items").delete_one({"id": int(fid)})
    col("free_item_stock").delete_many({"free_item_id": int(fid)})


def get_free_stock_count(fid):
    return col("free_item_stock").count_documents({"free_item_id": int(fid), "is_claimed": 0})


def add_free_stock(fid, items: list):
    docs = []
    for item in items:
        if str(item).strip():
            docs.append(_new("free_item_stock", free_item_id=int(fid), data=str(item).strip(),
                is_claimed=0, claimed_by=None, claimed_at=None, added_at=now_iso()))
    if docs: col("free_item_stock").insert_many(docs)
    return len(docs)


def has_user_claimed_free_item(user_id):
    return bool((_user(user_id) or {}).get("claimed_free_item"))


def claim_free_item(user_id, fid):
    if has_user_claimed_free_item(user_id): return False, "already_claimed"
    row = col("free_item_stock").find_one_and_update(
        {"free_item_id": int(fid), "is_claimed": 0},
        {"$set": {"is_claimed": 1, "claimed_by": int(user_id), "claimed_at": now_iso()}},
    )
    if not row: return False, "out_of_stock"
    col("users").update_one({"user_id": int(user_id)}, {"$set": {"claimed_free_item": 1}})
    return True, row.get("data")


# ── deposits ─────────────────────────────────────────────────────────────────
def get_unique_expected_amount(base_amount: float, network="TRC20"):
    used = {round(x.get("expected_usdt", 0), 3) for x in
            col("deposit_requests").find({"status": "pending"}, {"expected_usdt": 1})}
    for i in range(1, 100):
        candidate = round(float(base_amount) + i / 1000, 3)
        if candidate not in used: return candidate
    for i in range(1, 10):
        candidate = round(float(base_amount) + i / 10, 1)
        if candidate not in used: return candidate
    return round(float(base_amount) + random.randint(1, 9) / 100, 2)


def create_deposit_request(user_id, requested_usdt, expected_usdt, expires_at,
                           network="TRC20", deposit_type="address", pay_uid="",
                           dep_note=""):
    did = next_id("deposit_requests")
    col("deposit_requests").insert_one({"id": did, "user_id": int(user_id),
        "requested_usdt": float(requested_usdt), "expected_usdt": float(expected_usdt),
        "network": network, "deposit_type": deposit_type, "pay_uid": pay_uid,
        "dep_note": dep_note, "tx_hash": "", "provider_order_id": "",
        "payment_url": "", "payment_amount_inr": 0.0, "payment_status": "",
        "provider_txn_id": "", "utr": "", "status": "pending",
        "binance_txid": None, "credited_at": None, "fail_reason": "",
        "created_at": now_iso(), "expires_at": expires_at})
    return did


def set_deposit_tx_hash(dep_id: int, tx_hash: str):
    col("deposit_requests").update_one({"id": int(dep_id)}, {"$set": {"tx_hash": tx_hash}})


def set_zapupi_order(dep_id: int, provider_order_id: str, payment_url: str,
                     payment_amount_inr: float):
    col("deposit_requests").update_one({"id": int(dep_id)}, {"$set": {
        "provider_order_id": provider_order_id,
        "payment_url": payment_url,
        "payment_amount_inr": float(payment_amount_inr),
        "payment_status": "created",
    }})


def get_deposit_by_provider_order(provider_order_id: str):
    if not provider_order_id:
        return None
    return _clean(col("deposit_requests").find_one(
        {"provider_order_id": str(provider_order_id).strip()}))


def update_zapupi_payment(dep_id: int, status: str, utr: str = "",
                          provider_txn_id: str = ""):
    col("deposit_requests").update_one({"id": int(dep_id)}, {"$set": {
        "payment_status": status or "",
        "utr": utr or "",
        "provider_txn_id": provider_txn_id or "",
    }})


def get_deposit(dep_id: int):
    return _clean(col("deposit_requests").find_one({"id": int(dep_id)}))


def cancel_deposit(dep_id: int):
    return col("deposit_requests").update_one(
        {"id": int(dep_id), "status": "pending"},
        {"$set": {"status": "cancelled"}}
    ).modified_count > 0


def get_pending_deposits():
    return _docs(col("deposit_requests").find({"status": "pending"}).sort("id", ASCENDING))


def get_pending_deposits_by_type(deposit_type: str):
    return _docs(col("deposit_requests").find(
        {"status": "pending", "deposit_type": deposit_type}).sort("id", ASCENDING))


def complete_deposit(dep_id, txid, provider_txn_id="", utr=""):
    """Atomically resolve one pending deposit so webhook retries cannot
    double-credit a wallet."""
    fields = {
        "status": "completed",
        "binance_txid": txid,
        "credited_at": now_iso(),
    }
    if provider_txn_id:
        fields["provider_txn_id"] = provider_txn_id
    if utr:
        fields["utr"] = utr
    result = col("deposit_requests").update_one(
        {"id": int(dep_id), "status": "pending"},
        {"$set": fields},
    )
    return result.modified_count == 1


def get_completed_deposit_by_txhash(tx_hash: str):
    if not tx_hash: return None
    return _clean(col("deposit_requests").find_one(
        {"status": "completed", "tx_hash": {"$regex": "^" + str(tx_hash).strip() + "$", "$options": "i"}}))


def mark_deposit_failed(dep_id, reason):
    col("deposit_requests").update_one({"id": int(dep_id)}, {"$set": {
        "status": "failed", "fail_reason": reason}})


def expire_old_deposits():
    now = now_iso()
    rows = _docs(col("deposit_requests").find({"status": "pending", "expires_at": {"$lt": now}}))
    col("deposit_requests").update_many({"status": "pending", "expires_at": {"$lt": now}},
                                        {"$set": {"status": "expired"}})
    return rows


def get_user_deposits(user_id, limit=10):
    return _docs(col("deposit_requests").find({"user_id": int(user_id)})
                 .sort("id", DESCENDING).limit(int(limit)))


def get_today_deposits():
    prefix = datetime.now().strftime("%Y-%m-%d")
    rows = _docs(col("deposit_requests").find(
        {"created_at": {"$regex": "^" + prefix}}).sort("id", DESCENDING))
    for row in rows:
        user = _user(row["user_id"]) or {}
        row["username"] = user.get("username", "")
        row["full_name"] = user.get("full_name", "")
    return rows


def get_today_deposits_all():
    return get_today_deposits()


# ── settings / stats ─────────────────────────────────────────────────────────
def get_setting(key, default=""):
    row = col("settings").find_one({"key": key})
    return row.get("value", default) if row else default


def get_setting_float(key, default=0.0):
    try: return float(get_setting(key, ""))
    except Exception: return default


def get_setting_int(key, default=0):
    try: return int(get_setting(key, ""))
    except Exception: return default


def set_setting(key, value):
    col("settings").update_one({"key": key}, {"$set": {"value": str(value)}}, upsert=True)


def _order_stats(match=None):
    pipe = ([{"$match": match}] if match else []) + [{"$group": {
        "_id": None, "count": {"$sum": 1}, "amount": {"$sum": "$amount_usdt"}}}]
    return next(iter(col("orders").aggregate(pipe)), {"count": 0, "amount": 0})


def get_stats():
    s = _order_stats({"refunded": {"$ne": 1}})
    dep = next(iter(col("deposit_requests").aggregate([{"$match": {"status": "completed"}},
        {"$group": {"_id": None, "amount": {"$sum": "$requested_usdt"}}}])), {})
    return {"users": col("users").count_documents({}),
            "orders": int(s.get("count", 0)),
            "revenue": float(s.get("amount", 0) or 0),
            "total_dep": float(dep.get("amount", 0) or 0)}


def get_today_stats():
    prefix = datetime.now().strftime("%Y-%m-%d")
    s = _order_stats({"created_at": {"$regex": "^" + prefix}, "refunded": {"$ne": 1}})
    d = next(iter(col("deposit_requests").aggregate([{"$match": {
        "created_at": {"$regex": "^" + prefix}, "status": "completed"}},
        {"$group": {"_id": None, "count": {"$sum": 1},
                    "amount": {"$sum": "$requested_usdt"}}}])), {})
    return {"ord_count": int(s.get("count", 0)),
            "ord_amount": float(s.get("amount", 0) or 0),
            "dep_count": int(d.get("count", 0)),
            "dep_amount": float(d.get("amount", 0) or 0)}


def get_daily_report(date_str: str):
    s = _order_stats({"created_at": {"$regex": "^" + date_str}, "refunded": {"$ne": 1}})
    d = next(iter(col("deposit_requests").aggregate([{"$match": {
        "credited_at": {"$regex": "^" + date_str}, "status": "completed"}},
        {"$group": {"_id": None, "count": {"$sum": 1},
                    "amount": {"$sum": "$requested_usdt"}}}])), {})
    failed = col("deposit_requests").count_documents({"created_at": {"$regex": "^" + date_str},
                                                       "status": {"$in": ["expired", "cancelled"]}})
    orders = _orders_with_user({"created_at": {"$regex": "^" + date_str},
                                "refunded": {"$ne": 1}})
    deposits = get_today_deposits() if date_str == datetime.now().strftime("%Y-%m-%d") else _docs(
        col("deposit_requests").find({"status": "completed", "credited_at": {"$regex": "^" + date_str}}))
    return {"date": date_str, "ord_count": int(s.get("count", 0)),
            "ord_amount": float(s.get("amount", 0) or 0),
            "dep_count": int(d.get("count", 0)),
            "dep_amount": float(d.get("amount", 0) or 0),
            "dep_failed": int(failed),
            "new_users": col("users").count_documents({"joined_at": {"$regex": "^" + date_str}}),
            "total_balance_now": float(next(iter(col("users").aggregate(
                [{"$group": {"_id": None, "amount": {"$sum": "$balance"}}}])), {}).get("amount", 0) or 0),
            "total_users_now": col("users").count_documents({}),
            "orders": orders, "deposits": deposits}


def get_today_deposit_stats():
    prefix = datetime.now().strftime("%Y-%m-%d")
    pipe = [{"$match": {"credited_at": {"$regex": "^" + prefix}}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}, "amount": {"$sum": "$requested_usdt"}}}]
    out = {"success_count": 0, "success_amt": 0, "failed_count": 0,
           "failed_amt": 0, "pending_count": 0, "pending_amt": 0}
    for x in col("deposit_requests").aggregate(pipe):
        k = x["_id"] or "pending"
        if k == "completed":
            out["success_count"] = int(x["count"])
            out["success_amt"] = float(x["amount"] or 0)
        elif k in ("expired", "cancelled", "failed"):
            out["failed_count"] += int(x["count"])
        elif k == "pending":
            out["pending_count"] = int(x["count"])
    return out


def get_all_time_deposit_stats():
    pipe = [{"$group": {"_id": "$status", "count": {"$sum": 1},
                        "amount": {"$sum": "$requested_usdt"}}}]
    out = {"success_count": 0, "success_amt": 0, "failed_count": 0, "pending_count": 0}
    for x in col("deposit_requests").aggregate(pipe):
        k = x["_id"] or "pending"
        if k == "completed":
            out["success_count"] = int(x["count"])
            out["success_amt"] = float(x["amount"] or 0)
        elif k in ("expired", "cancelled", "failed"):
            out["failed_count"] += int(x["count"])
        elif k == "pending":
            out["pending_count"] = int(x["count"])
    return out


def get_all_deposits_list(limit=50000):
    rows = _docs(col("deposit_requests").find().sort("id", DESCENDING).limit(int(limit)))
    for row in rows:
        row["username"] = (_user(row["user_id"]) or {}).get("username", "")
    return rows


# ── admins / tickets / referrals ─────────────────────────────────────────────
def get_extra_admins():
    return [int(x["user_id"]) for x in col("extra_admins").find({}, {"user_id": 1})]


def add_extra_admin(user_id):
    col("extra_admins").update_one({"user_id": int(user_id)}, {"$set": {"user_id": int(user_id)}}, upsert=True)


def remove_extra_admin(user_id):
    col("extra_admins").delete_one({"user_id": int(user_id)})


def create_ticket(user_id, subject):
    tid = next_id("support_tickets")
    now = now_iso()
    col("support_tickets").insert_one({"id": tid, "user_id": int(user_id), "subject": subject,
        "status": "open", "created_at": now, "updated_at": now})
    return tid


def get_ticket(tid):
    return _clean(col("support_tickets").find_one({"id": int(tid)}))


def get_user_tickets(user_id):
    return _docs(col("support_tickets").find({"user_id": int(user_id)}).sort("id", DESCENDING))


def get_open_tickets():
    return _docs(col("support_tickets").find({"status": "open"}).sort("id", DESCENDING))


def get_all_tickets():
    return _docs(col("support_tickets").find().sort("id", DESCENDING))


def add_ticket_message(ticket_id, sender_id, message, is_admin=False):
    col("ticket_messages").insert_one(_new("ticket_messages",
        ticket_id=int(ticket_id), sender_id=int(sender_id), is_admin=1 if is_admin else 0,
        message=message, sent_at=now_iso()))
    col("support_tickets").update_one({"id": int(ticket_id)}, {"$set": {"updated_at": now_iso()}})


def get_ticket_messages(ticket_id):
    return _docs(col("ticket_messages").find({"ticket_id": int(ticket_id)}).sort("id", ASCENDING))


def close_ticket(tid):
    col("support_tickets").update_one({"id": int(tid)}, {"$set": {"status": "closed", "updated_at": now_iso()}})


def get_user_by_referral_code(code):
    return _clean(col("users").find_one({"referral_code": code}))


def set_referred_by(user_id, referrer_id):
    col("users").update_one({"user_id": int(user_id), "referred_by": None},
                            {"$set": {"referred_by": int(referrer_id)}})
    if not col("referrals").find_one({"referred_id": int(user_id)}):
        col("referrals").insert_one(_new("referrals", referrer_id=int(referrer_id),
            referred_id=int(user_id), bonus_paid=0.0, created_at=now_iso()))


def get_referral_count(user_id):
    return col("referrals").count_documents({"referrer_id": int(user_id)})


def credit_referral_deposit_bonus(user_id, amount):
    user = _user(user_id) or {}
    ref_id = user.get("referred_by")
    bonus = round(config.REFERRAL_BONUS_USDT, 6) if ref_id and float(amount) >= 1 else 0
    if not bonus:
        return None, 0
    update_balance(ref_id, bonus, "referral_bonus", "deposit", user_id)
    col("referrals").update_one(
        {"referrer_id": int(ref_id), "referred_id": int(user_id)},
        {"$inc": {"bonus_paid": bonus}},
    )
    return int(ref_id), bonus


def promote_vip(user_id):
    col("users").update_one({"user_id": int(user_id)}, {"$set": {"is_vip": 1}})


# ── coupons / cart ───────────────────────────────────────────────────────────
def get_coupons():
    return _docs(col("coupons").find().sort("id", DESCENDING))


def add_coupon(code, discount, max_uses):
    cid = next_id("coupons")
    col("coupons").insert_one({"id": cid, "code": code, "discount": int(discount),
        "max_uses": int(max_uses), "used_count": 0, "is_active": 1, "created_at": now_iso()})
    return cid


def toggle_coupon(cid):
    row = col("coupons").find_one({"id": int(cid)})
    if not row: return None
    val = 0 if row.get("is_active", 1) else 1
    col("coupons").update_one({"id": int(cid)}, {"$set": {"is_active": val}})
    return val


def delete_coupon(cid):
    col("coupons").delete_one({"id": int(cid)})
    col("coupon_uses").delete_many({"coupon_id": int(cid)})


def validate_coupon(code, user_id):
    coupon = col("coupons").find_one({"code": code, "is_active": 1})
    if not coupon or coupon.get("used_count", 0) >= coupon.get("max_uses", 0):
        return None
    if col("coupon_uses").find_one({"coupon_id": coupon["id"], "user_id": int(user_id)}):
        return None
    return _clean(coupon)


def apply_coupon(coupon_id, user_id):
    r = col("coupon_uses").insert_one(_new("coupon_uses", coupon_id=int(coupon_id),
        user_id=int(user_id), used_at=now_iso()))
    col("coupons").update_one({"id": int(coupon_id)}, {"$inc": {"used_count": 1}})
    return bool(r.inserted_id)


def add_to_cart(user_id, product_id, qty=1):
    col("cart_items").update_one({"user_id": int(user_id), "product_id": int(product_id)},
        {"$set": {"user_id": int(user_id), "product_id": int(product_id),
                  "quantity": int(qty), "added_at": now_iso()},
         "$setOnInsert": {"id": next_id("cart_items")}}, upsert=True)


def get_cart(user_id):
    return _docs(col("cart_items").find({"user_id": int(user_id)}).sort("id", ASCENDING))


def get_cart_item(user_id, product_id):
    return _clean(col("cart_items").find_one({"user_id": int(user_id), "product_id": int(product_id)}))


def set_cart_qty(user_id, product_id, qty):
    if int(qty) <= 0: return remove_cart_item(user_id, product_id)
    col("cart_items").update_one({"user_id": int(user_id), "product_id": int(product_id)},
                                 {"$set": {"quantity": int(qty)}})


def remove_cart_item(user_id, product_id):
    col("cart_items").delete_one({"user_id": int(user_id), "product_id": int(product_id)})


def clear_cart(user_id):
    col("cart_items").delete_many({"user_id": int(user_id)})


# ── reseller / withdrawals ───────────────────────────────────────────────────
def is_reseller(user_id):
    return bool(col("resellers").find_one({"user_id": int(user_id), "approved": 1}))


def add_reseller(user_id):
    col("resellers").update_one({"user_id": int(user_id)},
        {"$setOnInsert": {"user_id": int(user_id), "approved": 0, "created_at": now_iso()}}, upsert=True)


def approve_reseller(user_id):
    col("resellers").update_one({"user_id": int(user_id)}, {"$set": {"approved": 1}}, upsert=True)


def revoke_reseller(user_id):
    col("resellers").update_one({"user_id": int(user_id)}, {"$set": {"approved": 0}})


def get_resellers():
    return _docs(col("resellers").find().sort("created_at", DESCENDING))


def add_reseller_earning(reseller_id, order_id, gross_margin, owner_cut, reseller_cut):
    eid = next_id("reseller_earnings")
    col("reseller_earnings").insert_one({"id": eid, "reseller_id": int(reseller_id),
        "order_id": int(order_id), "gross_margin": float(gross_margin),
        "owner_cut": float(owner_cut), "reseller_cut": float(reseller_cut),
        "status": "pending", "created_at": now_iso(),
        "available_at": (datetime.now() + timedelta(days=7)).isoformat()})
    return eid


def mature_reseller_earnings():
    col("reseller_earnings").update_many(
        {"status": "pending", "available_at": {"$lte": now_iso()}},
        {"$set": {"status": "available"}})


def get_reseller_balance_summary(reseller_id):
    mature_reseller_earnings()
    rows = list(col("reseller_earnings").find({"reseller_id": int(reseller_id)}))
    return {"pending": sum(x.get("reseller_cut", 0) for x in rows if x.get("status") == "pending"),
            "available": sum(x.get("reseller_cut", 0) for x in rows if x.get("status") == "available"),
            "withdrawn": sum(x.get("reseller_cut", 0) for x in rows if x.get("status") == "withdrawn")}


def create_withdraw_request(user_id, amount):
    wid = next_id("withdraw_requests")
    col("withdraw_requests").insert_one({"id": wid, "user_id": int(user_id),
        "amount": float(amount), "status": "pending", "requested_at": now_iso(),
        "processed_at": None})
    return wid


def get_pending_withdraw_requests():
    return _docs(col("withdraw_requests").find({"status": "pending"}).sort("id", ASCENDING))


def get_withdraw_request(wid):
    return _clean(col("withdraw_requests").find_one({"id": int(wid)}))


def mark_withdraw_earnings_consumed(reseller_id, amount):
    remaining = float(amount)
    for row in col("reseller_earnings").find({"reseller_id": int(reseller_id), "status": "available"}).sort("id", ASCENDING):
        if remaining <= 0: break
        take = min(remaining, float(row.get("reseller_cut", 0)))
        remaining -= take
        col("reseller_earnings").update_one({"id": row["id"]}, {"$set": {"status": "withdrawn"}})


def process_withdraw_request(wid, approve):
    row = get_withdraw_request(wid)
    if not row or row.get("status") != "pending": return None
    status = "approved" if approve else "rejected"
    col("withdraw_requests").update_one({"id": int(wid)}, {"$set": {
        "status": status, "processed_at": now_iso()}})
    return get_withdraw_request(wid)


# ── refunds ───────────────────────────────────────────────────────────────────
def create_refund_request(user_id: int, order_id: int, reason: str):
    rid = next_id("refund_requests")
    col("refund_requests").insert_one({"id": rid, "user_id": int(user_id),
        "order_id": int(order_id), "reason": reason, "status": "pending",
        "admin_note": "", "created_at": now_iso(), "resolved_at": None})
    return rid


def get_refund_request(rid):
    return _clean(col("refund_requests").find_one({"id": int(rid)}))


def get_user_refund_request_for_order(user_id, order_id):
    return _clean(col("refund_requests").find_one(
        {"user_id": int(user_id), "order_id": int(order_id),
         "status": {"$in": ["pending", "approved"]}},
        sort=[("id", DESCENDING)]))


def get_pending_refund_requests():
    rows = _docs(col("refund_requests").find({"status": "pending"}).sort("id", ASCENDING))
    for row in rows:
        user, order = _user(row["user_id"]) or {}, get_order(row["order_id"]) or {}
        row.update(username=user.get("username", ""), full_name=user.get("full_name", ""),
                   product_name=order.get("product_name", ""),
                   amount_usdt=order.get("amount_usdt", 0))
    return rows


def get_all_refund_requests(limit=1000):
    rows = _docs(col("refund_requests").find().sort("id", DESCENDING).limit(int(limit)))
    for row in rows:
        user, order = _user(row["user_id"]) or {}, get_order(row["order_id"]) or {}
        row.update(username=user.get("username", ""), full_name=user.get("full_name", ""),
                   product_name=order.get("product_name", ""),
                   amount_usdt=order.get("amount_usdt", 0))
    return rows


def get_refund_request_full(rid):
    req = get_refund_request(rid)
    if not req: return None
    req["order"] = get_order(req["order_id"])
    req["user"] = get_user(req["user_id"])
    stock = col("stock_items").find_one({"order_id": req["order_id"]}, {"data": 1})
    req["credential"] = (stock or {}).get("data", "")
    return req


def approve_refund_request(rid):
    req = get_refund_request(rid)
    if not req or req.get("status") != "pending": return None, None
    order = refund_order(req["order_id"])
    if not order: return None, None
    col("refund_requests").update_one({"id": int(rid)}, {"$set": {
        "status": "approved", "resolved_at": now_iso()}})
    return get_refund_request(rid), order


def reject_refund_request(rid, admin_note=""):
    req = get_refund_request(rid)
    if not req or req.get("status") != "pending": return None
    col("refund_requests").update_one({"id": int(rid)}, {"$set": {
        "status": "rejected", "admin_note": admin_note, "resolved_at": now_iso()}})
    return get_refund_request(rid)


def add_refund_message(refund_id, sender_id, message, is_admin=False):
    col("refund_messages").insert_one(_new("refund_messages",
        refund_id=int(refund_id), sender_id=int(sender_id), is_admin=1 if is_admin else 0,
        message=message, sent_at=now_iso()))


def get_refund_messages(refund_id):
    return _docs(col("refund_messages").find({"refund_id": int(refund_id)}).sort("id", ASCENDING))


# ── history / web admin / restock ────────────────────────────────────────────
def get_user_full_history(user_id):
    orders = get_user_orders(user_id, 10000)
    deposits = get_user_deposits(user_id, 10000)
    out = []
    for x in orders:
        out.append({"type": "order", "id": x.get("id"), "created_at": x.get("created_at"),
                    "amount": x.get("amount_usdt", 0), "extra": "",
                    "status": x.get("status"), "product_name": x.get("product_name", "")})
    for x in deposits:
        out.append({"type": "deposit", "id": x.get("id"), "created_at": x.get("created_at"),
                    "amount": x.get("requested_usdt", 0), "extra": x.get("network", ""),
                    "status": x.get("status"), "product_name": ""})
    return sorted(out, key=lambda x: x.get("created_at", ""), reverse=True)


def manual_credit_deposit(user_id, amount, txid="MANUAL", network="MANUAL"):
    did = create_deposit_request(user_id, amount, amount, now_iso(), network, "manual")
    set_deposit_tx_hash(did, txid)
    complete_deposit(did, txid)
    update_balance(user_id, amount, "manual_deposit", "deposit", did)
    return did


def get_web_admin(username):
    return _clean(col("web_admins").find_one({"username": username}))


def create_web_admin(username, password_hash):
    aid = next_id("web_admins")
    col("web_admins").insert_one({"id": aid, "username": username,
        "password_hash": password_hash, "created_at": now_iso()})
    return aid


def add_restock_request(product_id: int, user_id: int):
    rid = next_id("restock_requests")
    col("restock_requests").update_one(
        {"product_id": int(product_id), "user_id": int(user_id), "notified": 0},
        {"$setOnInsert": {"id": rid, "product_id": int(product_id),
                          "user_id": int(user_id), "notified": 0, "created_at": now_iso()}},
        upsert=True)
    return rid


def get_pending_restock_requesters(product_id: int):
    return [int(x["user_id"]) for x in col("restock_requests").find(
        {"product_id": int(product_id), "notified": 0}, {"user_id": 1})]


def mark_restock_notified(product_id: int):
    col("restock_requests").update_many({"product_id": int(product_id), "notified": 0},
                                        {"$set": {"notified": 1}})


def mark_restock_request_notified(product_id: int, user_id: int):
    """Mark one user's request only after their Telegram notification succeeds."""
    col("restock_requests").update_one(
        {"product_id": int(product_id), "user_id": int(user_id), "notified": 0},
        {"$set": {"notified": 1}},
    )


def claim_low_stock_alert(product_id: int, stock_count: int, threshold: int) -> bool:
    """Edge-trigger low-stock alerts and re-arm after stock recovers."""
    pid = int(product_id)
    is_low = int(stock_count) > 0 and int(stock_count) < int(threshold)
    product = col("products").find_one({"id": pid}, {"low_stock_alert_sent": 1})
    if not product:
        return False
    sent = bool(product.get("low_stock_alert_sent", 0))
    if is_low and not sent:
        result = col("products").update_one(
            {"id": pid, "low_stock_alert_sent": {"$ne": 1}},
            {"$set": {"low_stock_alert_sent": 1}},
        )
        return result.modified_count > 0
    if not is_low and sent:
        col("products").update_one(
            {"id": pid}, {"$set": {"low_stock_alert_sent": 0}}
        )
    return False

