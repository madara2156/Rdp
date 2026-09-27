"""Shared helpers for the web version of the Telegram Account panel.

The Telegram admin panel stores its data in the MongoDB collections owned by
``otp_module``/``otp_admin``.  Keeping the web implementation here means both
interfaces use the same records and the same price/rate rules.
"""

import asyncio
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timedelta

from mongo_client import col, next_id, now_iso, strip_id


# Web OTP login flows keep the Telethon client on the same event loop between
# "send code" and "verify code" requests.  Telethon clients are loop-bound, so
# creating a new asyncio.run() loop for the second request would break login.
_LOGIN_FLOWS = {}
_LOGIN_LOCK = threading.RLock()
_LOGIN_TTL = 15 * 60


def _flow_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _cleanup_flow(flow, stop=True):
    if not flow:
        return
    loop = flow.get("loop")
    thread = flow.get("thread")
    if stop and loop and loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2)


def _prune_login_flows():
    now = time.time()
    stale = []
    with _LOGIN_LOCK:
        for flow_id, flow in list(_LOGIN_FLOWS.items()):
            if now - flow.get("created_at", now) > _LOGIN_TTL:
                stale.append((flow_id, flow))
                _LOGIN_FLOWS.pop(flow_id, None)
    for _flow_id, flow in stale:
        try:
            _run_on_flow(flow, _disconnect_client(flow["client"]))
        except Exception:
            pass
        _cleanup_flow(flow)


async def _disconnect_client(client):
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass


def _run_on_flow(flow, coroutine, timeout=120):
    future = asyncio.run_coroutine_threadsafe(coroutine, flow["loop"])
    return future.result(timeout=timeout)


async def _finish_login(flow):
    """Complete login, serialize the authenticated account, then close flow."""
    client = flow["client"]
    otp = _otp()
    country, icon = otp.country_from_phone(flow["phone"])
    if flow.get("country"):
        country = flow["country"]
        icon = flow.get("icon") or icon
    if not country or country == "Unknown":
        raise ValueError("country_required")
    year = flow.get("year")
    if not year:
        try:
            year = await otp.detect_account_year(client)
        except Exception:
            year = datetime.now().year
    if not year:
        year = datetime.now().year
    price = auto_price(country, year)
    if price is None:
        price = flow.get("price")
    if not price or int(price) <= 0:
        raise ValueError("price_required")
    session_string = client.session.save()
    _admin_module()._upsert_stock(
        flow["phone"], session_string, country, icon, int(year), int(price),
        flow.get("twofa") or "None",
    )
    return {
        "phone": flow["phone"], "country": country, "year": int(year),
        "price": int(price),
    }


async def _complete_login(flow, code=None, password=None):
    from telethon.errors import SessionPasswordNeededError, PhoneCodeExpiredError
    client = flow["client"]
    if flow.get("needs_2fa"):
        await client.sign_in(password=password or "")
        flow["twofa"] = password or "None"
    else:
        try:
            await client.sign_in(
                flow["phone"], code,
                phone_code_hash=flow["phone_code_hash"],
            )
        except SessionPasswordNeededError:
            flow["needs_2fa"] = True
            return {"needs_2fa": True}
        except PhoneCodeExpiredError:
            try:
                sent = await client.send_code_request(flow["phone"])
                flow["phone_code_hash"] = sent.phone_code_hash
            except Exception:
                pass
            return {"error": "otp_expired_resend"}
    result = await _finish_login(flow)
    await client.disconnect()
    return {"complete": True, **result}


def start_phone_login(owner, phone, price="", country="", year="", icon=""):
    _prune_login_flows()
    phone = str(phone).strip().replace(" ", "").lstrip("+")
    if not phone.isdigit() or len(phone) < 6:
        raise ValueError("invalid phone")
    if price:
        price = int(price)
        if price <= 0:
            raise ValueError("invalid price")
    year = int(year) if year else None
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_flow_loop, args=(loop,),
                              daemon=True, name="web-tg-login")
    thread.start()
    flow = {
        "id": uuid.uuid4().hex, "owner": owner, "phone": phone,
        "price": price, "country": str(country).strip(),
        "year": year, "icon": str(icon).strip(), "loop": loop,
        "thread": thread, "created_at": time.time(),
    }

    async def send_code():
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        client = TelegramClient(StringSession(), _otp().API_ID, _otp().API_HASH)
        await client.connect()
        sent = await client.send_code_request(phone)
        return client, sent.phone_code_hash

    try:
        client, phone_code_hash = _run_on_flow(flow, send_code())
        flow["client"] = client
        flow["phone_code_hash"] = phone_code_hash
        with _LOGIN_LOCK:
            _LOGIN_FLOWS[flow["id"]] = flow
        return {"flow_id": flow["id"], "phone": phone}
    except Exception:
        _cleanup_flow(flow)
        raise


def verify_phone_login(owner, flow_id, code="", password=""):
    _prune_login_flows()
    with _LOGIN_LOCK:
        flow = _LOGIN_FLOWS.get(str(flow_id))
    if not flow or flow.get("owner") != owner:
        raise ValueError("login_flow_expired")
    try:
        result = _run_on_flow(
            flow, _complete_login(flow, code=code, password=password)
        )
        if result.get("error"):
            return result
        if result.get("needs_2fa"):
            return result
        with _LOGIN_LOCK:
            _LOGIN_FLOWS.pop(flow["id"], None)
        _cleanup_flow(flow)
        return result
    except Exception:
        with _LOGIN_LOCK:
            _LOGIN_FLOWS.pop(flow["id"], None)
        try:
            _run_on_flow(flow, _disconnect_client(flow.get("client")))
        except Exception:
            pass
        _cleanup_flow(flow)
        raise


def cancel_phone_login(owner, flow_id):
    with _LOGIN_LOCK:
        flow = _LOGIN_FLOWS.get(str(flow_id))
        if not flow or flow.get("owner") != owner:
            return False
        _LOGIN_FLOWS.pop(str(flow_id), None)
    try:
        _run_on_flow(flow, _disconnect_client(flow.get("client")))
    except Exception:
        pass
    _cleanup_flow(flow)
    return True


def stock():
    return col("otp_stock")


def orders():
    return col("otp_orders")


def prices():
    return col("otp_auto_prices")


def settings():
    return col("otp_settings")


def countries():
    return col("otp_custom_countries")


def _otp():
    import otp_module
    return otp_module


def _admin_module():
    import otp_admin
    return otp_admin


def usdt_rate():
    return _otp().get_usdt_rate()


def set_usdt_rate(value):
    value = float(value)
    if value <= 0:
        raise ValueError("rate must be positive")
    _otp().set_setting("usdt_rate", value)
    return value


def auto_price(country, year):
    doc = prices().find_one({"country": country, "year": str(year)})
    if not doc:
        doc = prices().find_one({"country": country, "year": {"$in": ["*", "Common"]}})
    return int(doc["price"]) if doc and doc.get("price") is not None else None


def stock_summary():
    rows = list(stock().aggregate([
        {"$group": {
            "_id": "$country_name",
            "icon": {"$first": "$country_icon"},
            "live": {"$sum": {"$cond": [{"$eq": ["$available", 1]}, 1, 0]}},
            "used": {"$sum": {"$cond": [{"$ne": ["$available", 1]}, 1, 0]}},
        }},
        {"$sort": {"_id": 1}},
    ]))
    return [{
        "country": r.get("_id") or "Unknown",
        "icon": r.get("icon") or "🌍",
        "available": int(r.get("live") or 0),
        "used": int(r.get("used") or 0),
    } for r in rows]


def country_detail(country):
    rows = list(stock().aggregate([
        {"$match": {"country_name": country}},
        {"$group": {
            "_id": {"year": "$account_year", "price": "$price"},
            "available": {"$sum": {"$cond": [{"$eq": ["$available", 1]}, 1, 0]}},
            "total": {"$sum": 1},
        }},
        {"$sort": {"_id.year": -1, "_id.price": 1}},
    ]))
    return [{
        "year": r["_id"].get("year"),
        "price": r["_id"].get("price"),
        "available": int(r.get("available") or 0),
        "total": int(r.get("total") or 0),
    } for r in rows]


def clear_country(country):
    result = stock().delete_many({"country_name": country})
    return int(result.deleted_count)


def set_country_availability(country, available):
    result = stock().update_many({"country_name": country},
                                 {"$set": {"available": 1 if available else 0}})
    return int(result.modified_count)


def price_rules():
    rows = list(prices().find(
        {}, {"_id": 0, "country": 1, "year": 1, "price": 1}
    ).sort([("country", 1), ("year", 1)]))
    return [{
        "country": r.get("country", ""),
        "year": r.get("year", ""),
        "price": int(r.get("price") or 0),
    } for r in rows]


def save_price_rule(country, year, price):
    country = str(country).strip()
    year = str(year).strip()
    price = int(price)
    if not country or not year or price <= 0:
        raise ValueError("country, year and a positive price are required")
    prices().update_one(
        {"country": country, "year": year},
        {"$set": {"price": price}},
        upsert=True,
    )
    query = {"country_name": country}
    if year not in ("*", "Common"):
        try:
            query["account_year"] = int(year)
        except ValueError:
            query["account_year"] = year
    stock().update_many(query, {"$set": {"price": price}})
    return {"country": country, "year": year, "price": price}


def clear_price_rules():
    return int(prices().delete_many({}).deleted_count)


def otp_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    def sum_for(match=None):
        pipeline = []
        if match:
            pipeline.append({"$match": match})
        pipeline.append({"$group": {
            "_id": None, "count": {"$sum": 1}, "revenue": {"$sum": "$price"}
        }})
        row = next(iter(orders().aggregate(pipeline)), None)
        return {
            "count": int((row or {}).get("count") or 0),
            "revenue": int((row or {}).get("revenue") or 0),
        }

    top = list(orders().aggregate([
        {"$group": {"_id": "$country", "count": {"$sum": 1}, "revenue": {"$sum": "$price"}}},
        {"$sort": {"revenue": -1}},
        {"$limit": 8},
    ]))
    return {
        "today": sum_for({"created_at": {"$regex": "^" + today}}),
        "week": sum_for({"created_at": {"$gte": week}}),
        "all": sum_for(),
        "countries": [{
            "country": r.get("_id") or "Unknown",
            "count": int(r.get("count") or 0),
            "revenue": int(r.get("revenue") or 0),
        } for r in top],
    }


def twofa_distribution():
    rows = list(stock().aggregate([
        {"$group": {"_id": "$twofa", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]))
    return [{
        "label": "None" if not r.get("_id") else (
            "Set" if r.get("_id") not in ("None", "none") else "None"
        ),
        "count": int(r.get("count") or 0),
    } for r in rows]


def update_twofa(phone, password):
    phone = str(phone).strip().lstrip("+")
    if not phone:
        raise ValueError("phone is required")
    password = str(password).strip() or "None"
    result = stock().update_many({"phone": phone}, {"$set": {"twofa": password}})
    return int(result.matched_count)


def storage_summary():
    rows = list(stock().find({}, {"_id": 0, "phone": 1, "session_string": 1}))
    return {
        "total": len(rows),
        "string_sessions": sum(1 for r in rows if r.get("session_string")),
        "phones": [str(r.get("phone") or "") for r in rows[:100]],
    }


def panel_summary():
    available = stock().count_documents({"available": 1})
    reserved = stock().count_documents({"available": {"$ne": 1}})
    sold, revenue = 0, 0
    row = next(iter(orders().aggregate([
        {"$group": {"_id": None, "count": {"$sum": 1}, "revenue": {"$sum": "$price"}}}
    ])), None)
    if row:
        sold, revenue = int(row.get("count") or 0), int(row.get("revenue") or 0)
    return {
        "available": int(available),
        "reserved_or_used": int(reserved),
        "sold": sold,
        "revenue_inr": revenue,
        "countries": len(stock().distinct("country_name", {"available": 1})),
        "usdt_rate": usdt_rate(),
    }


def add_manual(phone, country, icon, year, price, twofa, session_string):
    phone = str(phone).strip().replace(" ", "").lstrip("+")
    if not phone.isdigit() or len(phone) < 6:
        raise ValueError("invalid phone")
    if not str(session_string).strip():
        raise ValueError("session string is required")
    year, price = int(year), int(price)
    if year < 1900 or price <= 0:
        raise ValueError("invalid year or price")
    _admin_module()._upsert_stock(
        phone, str(session_string).strip(), str(country).strip(),
        str(icon).strip() or "🌍", year, price, str(twofa).strip() or "None",
    )
    return phone


async def _test_rows(rows):
    otp = _otp()
    alive, dead = 0, []
    for row in rows:
        phone = row.get("phone")
        client = None
        try:
            client, _ = otp._client_for_stock(row)
            await client.connect()
            ok = await client.is_user_authorized()
            if ok:
                alive += 1
            else:
                dead.append(phone)
        except Exception:
            dead.append(phone)
        finally:
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass
    return {"alive": alive, "dead": len(dead), "dead_phones": dead}


def test_available():
    rows = list(stock().find({"available": 1}, {
        "_id": 0, "phone": 1, "session_string": 1, "session_file": 1
    }))
    return asyncio.run(_test_rows(rows))


def delete_dead(phones=None):
    if not phones:
        result = test_available()
        phones = result["dead_phones"]
    phones = [str(p).lstrip("+") for p in phones if p]
    if not phones:
        return {"deleted": 0, "phones": []}
    result = stock().delete_many({"phone": {"$in": phones}})
    return {"deleted": int(result.deleted_count), "phones": phones}


def _safe_extract(zip_path, target):
    with zipfile.ZipFile(zip_path) as archive:
        root = os.path.realpath(target)
        for info in archive.infolist():
            destination = os.path.realpath(os.path.join(target, info.filename))
            if destination != root and not destination.startswith(root + os.sep):
                raise ValueError("zip contains an unsafe path")
        archive.extractall(target)


async def _scan_session_files(extracted):
    otp = _otp()
    from telethon.tl.functions.account import GetPasswordRequest
    found = []
    for root, _dirs, files in os.walk(extracted):
        for filename in files:
            if not filename.endswith(".session"):
                continue
            path = os.path.join(root, filename)
            client = None
            try:
                client, _ = otp._client_for_stock({"session_file": path[:-8]})
                await client.connect()
                if not await client.is_user_authorized():
                    continue
                me = await client.get_me()
                phone = getattr(me, "phone", None)
                if not phone:
                    continue
                country, icon = otp.country_from_phone(phone)
                try:
                    year = await otp.detect_account_year(client)
                except Exception:
                    year = datetime.now().year
                try:
                    password_state = await client(GetPasswordRequest())
                    has_2fa = bool(password_state.has_password)
                except Exception:
                    has_2fa = False
                session_string = client.session.save()
                found.append({
                    "phone": str(phone).lstrip("+"),
                    "country": country,
                    "icon": icon,
                    "year": int(year),
                    "has_2fa": has_2fa,
                    "session_string": session_string,
                })
            except Exception:
                continue
            finally:
                if client:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
    return found


def add_zip(file_storage, price="", country_override="", year_override="", twofa=""):
    """Scan an uploaded ZIP and store authenticated sessions in MongoDB.

    Country/year are detected from the account where possible.  Overrides are
    useful for an unknown country or a failed year lookup.  A supplied 2FA
    value is applied to every imported account; this is intentionally explicit
    because Telegram never reveals an existing 2FA password.
    """
    tempdir = tempfile.mkdtemp(prefix="web_tgp_")
    zip_path = os.path.join(tempdir, "upload.zip")
    extracted = os.path.join(tempdir, "extracted")
    os.makedirs(extracted, exist_ok=True)
    try:
        file_storage.save(zip_path)
        _safe_extract(zip_path, extracted)
        scanned = asyncio.run(_scan_session_files(extracted))
        added, skipped, errors = 0, [], []
        for item in scanned:
            phone = item["phone"]
            country = str(country_override).strip() if (
                item["country"] == "Unknown" and country_override
            ) else item["country"]
            year = int(year_override) if year_override else item["year"]
            item_price = auto_price(country, year)
            if item_price is None and price:
                item_price = int(price)
            if item_price is None:
                existing = stock().find_one({"country_name": country}, {"price": 1})
                item_price = (existing or {}).get("price")
            if not country or country == "Unknown":
                skipped.append(phone)
                errors.append(f"+{phone}: country required")
                continue
            if not item_price or int(item_price) <= 0:
                skipped.append(phone)
                errors.append(f"+{phone}: price required")
                continue
            try:
                _admin_module()._upsert_stock(
                    phone, item["session_string"], country, item["icon"],
                    year, int(item_price), str(twofa).strip() or (
                        "Required" if item["has_2fa"] else "None"
                    ),
                )
                added += 1
            except Exception as exc:
                skipped.append(phone)
                errors.append(f"+{phone}: {exc}")
        return {
            "scanned": len(scanned), "added": added,
            "skipped": skipped, "errors": errors[:50],
        }
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)