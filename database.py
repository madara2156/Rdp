"""
NEXUS STORE BOT — Database Layer
SQLite with WAL mode for concurrent access
"""

import sqlite3
import random
import string
from datetime import datetime, timedelta

DB_PATH = "nexus_store.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id          INTEGER PRIMARY KEY,
        username         TEXT    DEFAULT '',
        full_name        TEXT    DEFAULT '',
        balance          REAL    DEFAULT 0.0,
        referral_code    TEXT    UNIQUE,
        referred_by      INTEGER,
        total_orders     INTEGER DEFAULT 0,
        total_spent_usdt REAL    DEFAULT 0.0,
        is_vip           INTEGER DEFAULT 0,
        is_banned        INTEGER DEFAULT 0,
        language         TEXT    DEFAULT '',
        joined_at        TEXT
    );

    CREATE TABLE IF NOT EXISTS categories (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        name      TEXT    NOT NULL,
        emoji     TEXT    DEFAULT '📺',
        is_active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS products (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id   INTEGER,
        name          TEXT    NOT NULL,
        emoji         TEXT    DEFAULT '🎬',
        description   TEXT    DEFAULT '',
        price_usdt    REAL    NOT NULL,
        duration      TEXT    DEFAULT '1 Month',
        stock_count   INTEGER DEFAULT 0,
        is_active     INTEGER DEFAULT 1,
        created_at    TEXT,
        FOREIGN KEY (category_id) REFERENCES categories(id)
    );

    CREATE TABLE IF NOT EXISTS stock_items (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        data       TEXT    NOT NULL,
        data_norm  TEXT    DEFAULT '',
        is_sold    INTEGER DEFAULT 0,
        sold_to    INTEGER,
        order_id   INTEGER,
        added_at   TEXT,
        sold_at    TEXT
    );

    CREATE TABLE IF NOT EXISTS orders (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id          INTEGER NOT NULL,
        product_id       INTEGER NOT NULL,
        product_name     TEXT,
        amount_usdt      REAL    NOT NULL,
        status           TEXT    DEFAULT 'completed',
        stock_item_id    INTEGER,
        coupon_code      TEXT,
        is_reseller_sale INTEGER DEFAULT 0,
        reminder_sent    INTEGER DEFAULT 0,
        refunded         INTEGER DEFAULT 0,
        created_at       TEXT
    );

    CREATE TABLE IF NOT EXISTS deposit_requests (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id        INTEGER NOT NULL,
        requested_usdt REAL    NOT NULL,
        expected_usdt  REAL    NOT NULL,
        network        TEXT    DEFAULT 'TRC20',
        deposit_type   TEXT    DEFAULT 'address',
        pay_uid        TEXT    DEFAULT '',
        dep_note       TEXT    DEFAULT '',
        tx_hash        TEXT    DEFAULT '',
        status         TEXT    DEFAULT 'pending',
        binance_txid   TEXT,
        credited_at    TEXT,
        created_at     TEXT,
        expires_at     TEXT
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_dep_txhash_completed
        ON deposit_requests(tx_hash) WHERE status='completed' AND tx_hash != '';

    CREATE TABLE IF NOT EXISTS free_items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        emoji       TEXT    DEFAULT '🎁',
        description TEXT    DEFAULT '',
        is_active   INTEGER DEFAULT 1,
        created_at  TEXT
    );

    CREATE TABLE IF NOT EXISTS free_item_stock (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        free_item_id INTEGER NOT NULL,
        data         TEXT    NOT NULL,
        is_claimed   INTEGER DEFAULT 0,
        claimed_by   INTEGER,
        claimed_at   TEXT,
        added_at     TEXT
    );

    CREATE TABLE IF NOT EXISTS support_tickets (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        subject    TEXT    NOT NULL,
        status     TEXT    DEFAULT 'open',
        created_at TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS ticket_messages (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        is_admin  INTEGER DEFAULT 0,
        message   TEXT    NOT NULL,
        sent_at   TEXT,
        FOREIGN KEY (ticket_id) REFERENCES support_tickets(id)
    );

    CREATE TABLE IF NOT EXISTS referrals (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER NOT NULL,
        referred_id INTEGER NOT NULL,
        bonus_paid  REAL    DEFAULT 0.0,
        created_at  TEXT
    );

    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS extra_admins (
        user_id INTEGER PRIMARY KEY
    );

    CREATE TABLE IF NOT EXISTS coupons (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        code       TEXT    UNIQUE NOT NULL,
        discount   INTEGER DEFAULT 10,
        max_uses   INTEGER DEFAULT 100,
        used_count INTEGER DEFAULT 0,
        is_active  INTEGER DEFAULT 1,
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS coupon_uses (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        coupon_id INTEGER NOT NULL,
        user_id   INTEGER NOT NULL,
        used_at   TEXT
    );

    CREATE TABLE IF NOT EXISTS cart_items (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity   INTEGER DEFAULT 1,
        added_at   TEXT
    );

    CREATE TABLE IF NOT EXISTS resellers (
        user_id    INTEGER PRIMARY KEY,
        approved   INTEGER DEFAULT 0,
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS reseller_earnings (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        reseller_id  INTEGER NOT NULL,
        order_id     INTEGER NOT NULL,
        gross_margin REAL    DEFAULT 0.0,
        owner_cut    REAL    DEFAULT 0.0,
        reseller_cut REAL    DEFAULT 0.0,
        status       TEXT    DEFAULT 'pending',
        created_at   TEXT,
        available_at TEXT
    );

    CREATE TABLE IF NOT EXISTS withdraw_requests (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        amount       REAL    NOT NULL,
        status       TEXT    DEFAULT 'pending',
        requested_at TEXT,
        processed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS refund_requests (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        order_id     INTEGER NOT NULL,
        reason       TEXT    DEFAULT '',
        status       TEXT    DEFAULT 'pending',
        admin_note   TEXT    DEFAULT '',
        created_at   TEXT,
        resolved_at  TEXT
    );

    CREATE TABLE IF NOT EXISTS refund_messages (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        refund_id  INTEGER NOT NULL,
        sender_id  INTEGER NOT NULL,
        is_admin   INTEGER DEFAULT 0,
        message    TEXT    NOT NULL,
        sent_at    TEXT
    );

    CREATE TABLE IF NOT EXISTS web_admins (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at    TEXT
    );
    """)

    # Migrations: add new columns if they don't exist
    _safe_add_column(c, "users",            "language",      "TEXT DEFAULT ''")
    _safe_add_column(c, "deposit_requests", "network",       "TEXT DEFAULT 'TRC20'")
    _safe_add_column(c, "deposit_requests", "deposit_type",  "TEXT DEFAULT 'address'")
    _safe_add_column(c, "deposit_requests", "pay_uid",       "TEXT DEFAULT ''")
    _safe_add_column(c, "orders",           "coupon_code",   "TEXT")
    _safe_add_column(c, "orders",           "is_reseller_sale","INTEGER DEFAULT 0")
    _safe_add_column(c, "orders",           "reminder_sent", "INTEGER DEFAULT 0")
    _safe_add_column(c, "orders",           "refunded",      "INTEGER DEFAULT 0")
    _safe_add_column(c, "stock_items",      "data_norm",     "TEXT DEFAULT ''")
    _safe_add_column(c, "refund_requests",  "admin_note",    "TEXT DEFAULT ''")
    _safe_add_column(c, "deposit_requests", "dep_note",      "TEXT DEFAULT ''")
    _safe_add_column(c, "deposit_requests", "tx_hash",       "TEXT DEFAULT ''")
    _safe_add_column(c, "deposit_requests", "fail_reason",   "TEXT DEFAULT ''")
    _safe_add_column(c, "deposit_requests", "provider_order_id", "TEXT DEFAULT ''")
    _safe_add_column(c, "deposit_requests", "payment_url",      "TEXT DEFAULT ''")
    _safe_add_column(c, "deposit_requests", "payment_amount_inr","REAL DEFAULT 0")
    _safe_add_column(c, "deposit_requests", "payment_status",   "TEXT DEFAULT ''")
    _safe_add_column(c, "deposit_requests", "provider_txn_id",  "TEXT DEFAULT ''")
    _safe_add_column(c, "deposit_requests", "utr",              "TEXT DEFAULT ''")
    _safe_add_column(c, "users",            "claimed_free_item", "INTEGER DEFAULT 0")
    _safe_add_column(c, "products",         "emoji_id",      "TEXT DEFAULT ''")
    _safe_add_column(c, "products",         "low_stock_alert_sent", "INTEGER DEFAULT 0")

    c.execute("""
    CREATE TABLE IF NOT EXISTS restock_requests (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        user_id    INTEGER NOT NULL,
        notified   INTEGER DEFAULT 0,
        created_at TEXT
    );
    """)
    c.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_deposit_provider_order
        ON deposit_requests(provider_order_id)
        WHERE provider_order_id != '';
    """)

    conn.commit()
    conn.close()

    # Bootstrap: make sure at least one category always exists, so admins
    # can add products immediately without a separate "create category" step.
    if not get_categories(active_only=False):
        add_category("General", "🛍️")

def _safe_add_column(cursor, table, col, typedef):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
    except Exception:
        pass

# ── User ──────────────────────────────────────────────────────────────────────

def _gen_ref():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def get_or_create_user(user_id: int, username: str = "", full_name: str = "") -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if row:
        conn.execute("UPDATE users SET username=?, full_name=? WHERE user_id=?",
                     (username or row["username"], full_name or row["full_name"], user_id))
        conn.commit()
        row2 = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return dict(row2)
    code = _gen_ref()
    while conn.execute("SELECT 1 FROM users WHERE referral_code=?", (code,)).fetchone():
        code = _gen_ref()
    conn.execute(
        "INSERT INTO users (user_id,username,full_name,referral_code,balance,language,joined_at) VALUES (?,?,?,?,0.0,'',?)",
        (user_id, username, full_name, code, datetime.now().isoformat())
    )
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row)

def get_user(user_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def user_exists(user_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row is not None

def get_user_language(user_id: int) -> str:
    conn = get_conn()
    row = conn.execute("SELECT language FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if row and row["language"]:
        return row["language"]
    return "en"

def set_user_language(user_id: int, lang: str):
    conn = get_conn()
    conn.execute("UPDATE users SET language=? WHERE user_id=?", (lang, user_id))
    conn.commit()
    conn.close()

def update_balance(user_id: int, delta: float, reason="adjustment",
                   reference_type="", reference_id=None):
    """Credit/debit a wallet. The extra reason/reference args exist so the
    merged TG Store (otp) module can call this with the same signature it
    used on the other bot; they are accepted and ignored here."""
    conn = get_conn()
    conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (delta, user_id))
    conn.commit()
    conn.close()
    return True

def debit_balance(user_id: int, amount: float, reason="purchase",
                  reference_type="", reference_id=None):
    """Atomically debit only when the user still has enough balance.
    Returns True when the debit happened, False when funds were insufficient."""
    amount = round(float(amount), 6)
    if amount < 0:
        raise ValueError("debit amount cannot be negative")
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
            (amount, user_id, amount))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def get_all_users():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users ORDER BY joined_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def ban_user(user_id: int, ban: bool):
    conn = get_conn()
    conn.execute("UPDATE users SET is_banned=? WHERE user_id=?", (1 if ban else 0, user_id))
    conn.commit()
    conn.close()

def search_users(query: str):
    conn = get_conn()
    q = f"%{query}%"
    rows = conn.execute(
        "SELECT * FROM users WHERE CAST(user_id AS TEXT) LIKE ? OR username LIKE ? OR full_name LIKE ? LIMIT 20",
        (q, q, q)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Categories ────────────────────────────────────────────────────────────────

def get_categories(active_only=True):
    conn = get_conn()
    q = "SELECT * FROM categories WHERE is_active=1" if active_only else "SELECT * FROM categories"
    rows = conn.execute(q + " ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_category(name, emoji):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO categories (name,emoji) VALUES (?,?)", (name, emoji))
    cid = c.lastrowid
    conn.commit()
    conn.close()
    return cid

def toggle_category(cid):
    conn = get_conn()
    conn.execute("UPDATE categories SET is_active = 1-is_active WHERE id=?", (cid,))
    conn.commit()
    conn.close()

def delete_category(cid, force=False):
    conn = get_conn()
    try:
        prods = conn.execute("SELECT COUNT(*) as n FROM products WHERE category_id=?", (cid,)).fetchone()["n"]
        if prods:
            if not force:
                return False
            # Force delete: re-home the products instead of deleting them
            # (deleting them would also destroy their order/stock history,
            # and the DB's foreign key constraint would block a raw DELETE
            # on this category anyway while products still point to it).
            general = conn.execute("SELECT id FROM categories WHERE name='General' AND id!=?", (cid,)).fetchone()
            if not general:
                cur = conn.cursor()
                cur.execute("INSERT INTO categories (name,emoji) VALUES ('General','🛍️')")
                general_id = cur.lastrowid
            else:
                general_id = general["id"]
            conn.execute("UPDATE products SET category_id=? WHERE category_id=?", (general_id, cid))
        conn.execute("DELETE FROM categories WHERE id=?", (cid,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()

def get_category(cid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None

# ── Products ──────────────────────────────────────────────────────────────────

def get_products(category_id=None, active_only=True):
    conn = get_conn()
    if category_id:
        rows = conn.execute(
            "SELECT * FROM products WHERE category_id=? AND is_active=1 ORDER BY id" if active_only
            else "SELECT * FROM products WHERE category_id=? ORDER BY id", (category_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM products WHERE is_active=1 ORDER BY id" if active_only
            else "SELECT * FROM products ORDER BY id"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_product(pid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def add_product(category_id, name, emoji, description, price_usdt, duration, emoji_id=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO products (category_id,name,emoji,description,price_usdt,duration,created_at,emoji_id) VALUES (?,?,?,?,?,?,?,?)",
        (category_id, name, emoji, description, price_usdt, duration, datetime.now().isoformat(), emoji_id)
    )
    pid = c.lastrowid
    conn.commit()
    conn.close()
    return pid

def update_product_emoji_id(pid, emoji_id):
    conn = get_conn()
    conn.execute("UPDATE products SET emoji_id=? WHERE id=?", (emoji_id, pid))
    conn.commit()
    conn.close()

def delete_product(pid):
    conn = get_conn()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()

# ── Stock ─────────────────────────────────────────────────────────────────────

def get_stock_count(product_id):
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) as n FROM stock_items WHERE product_id=? AND is_sold=0", (product_id,)).fetchone()["n"]
    conn.close()
    return n

def refresh_stock_count(product_id):
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) as n FROM stock_items WHERE product_id=? AND is_sold=0", (product_id,)).fetchone()["n"]
    conn.execute("UPDATE products SET stock_count=? WHERE id=?", (n, product_id))
    conn.commit()
    conn.close()

def add_stock(product_id, items: list):
    conn = get_conn()
    now = datetime.now().isoformat()
    existing = {r["data_norm"] for r in conn.execute("SELECT data_norm FROM stock_items WHERE product_id=?", (product_id,)).fetchall()}
    to_add = []
    duplicate_lines = []
    for item in items:
        norm = item.strip().lower()
        if norm in existing:
            duplicate_lines.append(item)
        else:
            to_add.append(item)
            existing.add(norm)
    for item in to_add:
        conn.execute(
            "INSERT INTO stock_items (product_id,data,data_norm,added_at) VALUES (?,?,?,?)",
            (product_id, item.strip(), item.strip().lower(), now)
        )
    conn.commit()
    conn.close()
    if to_add:
        refresh_stock_count(product_id)
    return {"added": len(to_add), "duplicates": len(duplicate_lines), "duplicate_lines": duplicate_lines}

# ── Free Items ────────────────────────────────────────────────────────────────

def create_free_item(name, emoji, description=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO free_items (name,emoji,description,created_at) VALUES (?,?,?,?)",
        (name, emoji, description, datetime.now().isoformat())
    )
    fid = c.lastrowid
    conn.commit()
    conn.close()
    return fid

def get_free_items(active_only=True):
    conn = get_conn()
    if active_only:
        rows = conn.execute("SELECT * FROM free_items WHERE is_active=1 ORDER BY id DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM free_items ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_free_item(fid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM free_items WHERE id=?", (fid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def toggle_free_item(fid):
    conn = get_conn()
    row = conn.execute("SELECT is_active FROM free_items WHERE id=?", (fid,)).fetchone()
    if not row:
        conn.close(); return None
    new_val = 0 if row["is_active"] else 1
    conn.execute("UPDATE free_items SET is_active=? WHERE id=?", (new_val, fid))
    conn.commit()
    conn.close()
    return new_val

def delete_free_item(fid):
    conn = get_conn()
    conn.execute("DELETE FROM free_items WHERE id=?", (fid,))
    conn.execute("DELETE FROM free_item_stock WHERE free_item_id=?", (fid,))
    conn.commit()
    conn.close()

def get_free_stock_count(fid):
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) as n FROM free_item_stock WHERE free_item_id=? AND is_claimed=0", (fid,)).fetchone()["n"]
    conn.close()
    return n

def add_free_stock(fid, items: list):
    conn = get_conn()
    now = datetime.now().isoformat()
    for item in items:
        item = item.strip()
        if not item:
            continue
        conn.execute(
            "INSERT INTO free_item_stock (free_item_id,data,added_at) VALUES (?,?,?)",
            (fid, item, now)
        )
    conn.commit()
    conn.close()
    return len(items)

def has_user_claimed_free_item(user_id):
    conn = get_conn()
    row = conn.execute("SELECT claimed_free_item FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return bool(row and row["claimed_free_item"])

def claim_free_item(user_id, fid):
    """Atomically claim one free-item stock line for this user.
    Returns (ok, data_or_reason). A user may claim only ONE free item, EVER."""
    conn = get_conn()
    c = conn.cursor()
    try:
        row = c.execute("SELECT claimed_free_item FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row and row["claimed_free_item"]:
            conn.close()
            return False, "already_claimed"
        stock_row = c.execute(
            "SELECT * FROM free_item_stock WHERE free_item_id=? AND is_claimed=0 LIMIT 1", (fid,)
        ).fetchone()
        if not stock_row:
            conn.close()
            return False, "out_of_stock"
        now = datetime.now().isoformat()
        c.execute(
            "UPDATE free_item_stock SET is_claimed=1, claimed_by=?, claimed_at=? WHERE id=?",
            (user_id, now, stock_row["id"])
        )
        c.execute("UPDATE users SET claimed_free_item=1 WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        return True, stock_row["data"]
    except Exception:
        conn.close()
        raise

def pop_stock(product_id, qty=1):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM stock_items WHERE product_id=? AND is_sold=0 LIMIT ?", (product_id, qty)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_stock_sold(item_id, user_id, order_id):
    conn = get_conn()
    conn.execute(
        "UPDATE stock_items SET is_sold=1, sold_to=?, order_id=?, sold_at=? WHERE id=?",
        (user_id, order_id, datetime.now().isoformat(), item_id)
    )
    conn.commit()
    conn.close()

def get_stock_items(product_id, include_sold=False, limit=50):
    conn = get_conn()
    q = "SELECT * FROM stock_items WHERE product_id=?" + ("" if include_sold else " AND is_sold=0") + " LIMIT ?"
    rows = conn.execute(q, (product_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def edit_stock_item(item_id, new_data):
    """Edit the credential/link text of ONE unsold stock item (e.g. fix a
    wrong password) without touching the rest of the batch."""
    conn = get_conn()
    row = conn.execute("SELECT is_sold FROM stock_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE stock_items SET data=?, data_norm=? WHERE id=?",
        (new_data, new_data.strip().lower(), item_id)
    )
    conn.commit()
    conn.close()
    return True

def remove_stock_item(item_id):
    conn = get_conn()
    row = conn.execute("SELECT product_id FROM stock_items WHERE id=?", (item_id,)).fetchone()
    conn.execute("DELETE FROM stock_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    if row:
        refresh_stock_count(row["product_id"])

def clear_stock(product_id):
    conn = get_conn()
    conn.execute("DELETE FROM stock_items WHERE product_id=? AND is_sold=0", (product_id,))
    conn.commit()
    conn.close()
    refresh_stock_count(product_id)

# ── Orders ────────────────────────────────────────────────────────────────────

def create_order(user_id, product_id, product_name, amount_usdt, stock_item_id=None,
                 coupon_code=None, is_reseller_sale=False, source="normal",
                 otp_order_id=None):
    # `source` and `otp_order_id` are accepted for compatibility with the
    # merged TG/OTP module.  SQLite keeps the common order schema; the source
    # specific details remain in the OTP MongoDB collection.
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO orders (user_id,product_id,product_name,amount_usdt,stock_item_id,"
        "coupon_code,is_reseller_sale,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (user_id, product_id, product_name, amount_usdt, stock_item_id,
         coupon_code, 1 if is_reseller_sale else 0, datetime.now().isoformat())
    )
    oid = c.lastrowid
    conn.execute("UPDATE users SET total_orders=total_orders+1, total_spent_usdt=total_spent_usdt+? WHERE user_id=?",
                 (amount_usdt, user_id))
    conn.commit()
    conn.close()
    refresh_stock_count(product_id)
    return oid

def get_user_orders(user_id, limit=20, offset=0):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?", (user_id, limit, offset)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_order_count(user_id):
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) c FROM orders WHERE user_id=?", (user_id,)).fetchone()["c"]
    conn.close()
    return n

def get_order(oid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_today_orders(limit=10000):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    rows = conn.execute(
        "SELECT o.*, u.username, s.data AS cred_data FROM orders o "
        "LEFT JOIN users u ON u.user_id=o.user_id "
        "LEFT JOIN stock_items s ON s.order_id=o.id "
        "WHERE o.created_at LIKE ? ORDER BY o.id DESC LIMIT ?", (f"{today}%", limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_orders(limit=1000000):
    conn = get_conn()
    rows = conn.execute(
        "SELECT o.*, u.username, s.data AS cred_data FROM orders o "
        "LEFT JOIN users u ON u.user_id=o.user_id "
        "LEFT JOIN stock_items s ON s.order_id=o.id "
        "ORDER BY o.id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def refund_order(oid):
    conn = get_conn()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not order or order["refunded"]:
        conn.close()
        return None
    conn.execute("UPDATE orders SET refunded=1 WHERE id=?", (oid,))
    conn.execute("UPDATE users SET balance=balance+?, total_spent_usdt=total_spent_usdt-? WHERE user_id=?",
                 (order["amount_usdt"], order["amount_usdt"], order["user_id"]))
    if order["stock_item_id"]:
        conn.execute("UPDATE stock_items SET is_sold=0, sold_to=NULL, order_id=NULL, sold_at=NULL WHERE id=?",
                     (order["stock_item_id"],))
        refresh_stock_count_conn(conn, order["product_id"])
    conn.commit()
    conn.close()
    return dict(order)

def refresh_stock_count_conn(conn, product_id):
    n = conn.execute("SELECT COUNT(*) as n FROM stock_items WHERE product_id=? AND is_sold=0", (product_id,)).fetchone()["n"]
    conn.execute("UPDATE products SET stock_count=? WHERE id=?", (n, product_id))

# ── Deposits ──────────────────────────────────────────────────────────────────

def get_unique_expected_amount(base_amount: float, network: str = "TRC20") -> float:
    """
    Generate a collision-free expected_usdt amount for a new deposit request.
    Supports 100+ concurrent users depositing the same base amount.

    Strategy:
      • Fine offsets  0.001 – 0.099  (99 slots, 3 decimal places)
      • Coarse fallback 0.10 – 0.90  (9 extra slots, if all fine slots used)
    Each candidate is checked against currently PENDING requests so the same
    expected amount is never assigned twice.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT expected_usdt FROM deposit_requests WHERE status='pending'",
    ).fetchall()
    conn.close()
    used = {round(r["expected_usdt"], 3) for r in rows}

    # Try fine offsets first: 0.001 → 0.099  (99 values)
    for i in range(1, 100):
        candidate = round(base_amount + i / 1000, 3)
        if candidate not in used:
            return candidate

    # Coarse fallback: 0.10 → 0.90  (9 more values)
    for i in range(1, 10):
        candidate = round(base_amount + i / 10, 1)
        if candidate not in used:
            return candidate

    # Last resort: random (should never happen in practice)
    import random as _rnd
    return round(base_amount + _rnd.randint(1, 9) / 100, 2)


def create_deposit_request(user_id, requested_usdt, expected_usdt, expires_at,
                           network="TRC20", deposit_type="address", pay_uid="", dep_note=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO deposit_requests "
        "(user_id,requested_usdt,expected_usdt,network,deposit_type,pay_uid,dep_note,created_at,expires_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, requested_usdt, expected_usdt, network, deposit_type, pay_uid, dep_note,
         datetime.now().isoformat(), expires_at)
    )
    did = c.lastrowid
    conn.commit()
    conn.close()
    return did

def set_zapupi_order(dep_id: int, provider_order_id: str, payment_url: str,
                     payment_amount_inr: float):
    conn = get_conn()
    conn.execute(
        "UPDATE deposit_requests SET provider_order_id=?, payment_url=?, "
        "payment_amount_inr=?, payment_status='created' WHERE id=?",
        (provider_order_id, payment_url, payment_amount_inr, dep_id),
    )
    conn.commit()
    conn.close()

def get_deposit_by_provider_order(provider_order_id: str):
    if not provider_order_id:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM deposit_requests WHERE provider_order_id=? LIMIT 1",
        (provider_order_id.strip(),),
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def update_zapupi_payment(dep_id: int, status: str, utr: str = "",
                          provider_txn_id: str = ""):
    conn = get_conn()
    conn.execute(
        "UPDATE deposit_requests SET payment_status=?, utr=?, provider_txn_id=? WHERE id=?",
        (status or "", utr or "", provider_txn_id or "", dep_id),
    )
    conn.commit()
    conn.close()

def set_deposit_tx_hash(dep_id: int, tx_hash: str):
    conn = get_conn()
    conn.execute("UPDATE deposit_requests SET tx_hash=? WHERE id=?", (tx_hash, dep_id))
    conn.commit()
    conn.close()

def get_deposit(dep_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM deposit_requests WHERE id=?", (dep_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_pending_deposits():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM deposit_requests WHERE status='pending' ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_pending_deposits_by_type(deposit_type: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM deposit_requests WHERE status='pending' AND deposit_type=? ORDER BY id",
        (deposit_type,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def complete_deposit(dep_id, txid, provider_txn_id="", utr=""):
    """Atomically resolve one pending deposit.

    Returning False means another webhook/poll/admin action already resolved
    it. This makes ZapUPI webhook retries safe and prevents double credits.
    """
    conn = get_conn()
    cur = conn.execute(
        "UPDATE deposit_requests SET status='completed', binance_txid=?, "
        "provider_txn_id=COALESCE(NULLIF(?, ''), provider_txn_id), "
        "utr=COALESCE(NULLIF(?, ''), utr), credited_at=? "
        "WHERE id=? AND status='pending'",
        (txid, provider_txn_id or "", utr or "", datetime.now().isoformat(), dep_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount == 1

def get_completed_deposit_by_txhash(tx_hash: str):
    """Return a COMPLETED deposit (any user) that already used this exact tx hash, or None.
    Used to block a transaction hash from being claimed/credited more than once."""
    if not tx_hash:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM deposit_requests WHERE status='completed' AND LOWER(tx_hash)=LOWER(?) LIMIT 1",
        (tx_hash.strip(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def mark_deposit_failed(dep_id: int, reason: str):
    conn = get_conn()
    conn.execute(
        "UPDATE deposit_requests SET status='failed', fail_reason=? WHERE id=?",
        (reason, dep_id)
    )
    conn.commit()
    conn.close()

def expire_old_deposits():
    conn = get_conn()
    now = datetime.now().isoformat()
    rows = conn.execute(
        "SELECT * FROM deposit_requests WHERE status='pending' AND expires_at<?", (now,)
    ).fetchall()
    if rows:
        conn.execute("UPDATE deposit_requests SET status='expired' WHERE status='pending' AND expires_at<?", (now,))
        conn.commit()
    conn.close()
    return [dict(r) for r in rows]

def get_user_deposits(user_id, limit=10):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM deposit_requests WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_today_deposits():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    rows = conn.execute(
        "SELECT dr.*, u.username FROM deposit_requests dr LEFT JOIN users u ON u.user_id=dr.user_id "
        "WHERE dr.status='completed' AND dr.credited_at LIKE ? ORDER BY dr.id DESC", (f"{today}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Settings ──────────────────────────────────────────────────────────────────

def get_setting(key, default=""):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def get_setting_float(key, default=0.0):
    v = get_setting(key, "")
    try: return float(v) if v else default
    except: return default

def get_setting_int(key, default=0):
    v = get_setting(key, "")
    try: return int(v) if v else default
    except: return default

def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()

# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats():
    conn = get_conn()
    users    = conn.execute("SELECT COUNT(*) as n FROM users").fetchone()["n"]
    orders   = conn.execute("SELECT COUNT(*) as n FROM orders WHERE refunded=0").fetchone()["n"]
    revenue  = conn.execute("SELECT COALESCE(SUM(amount_usdt),0) as s FROM orders WHERE refunded=0").fetchone()["s"]
    deposits = conn.execute("SELECT COALESCE(SUM(requested_usdt),0) as s FROM deposit_requests WHERE status='completed'").fetchone()["s"]
    total_dep= conn.execute("SELECT COALESCE(SUM(requested_usdt),0) as s FROM deposit_requests WHERE status='completed'").fetchone()["s"]
    conn.close()
    return {"users": users, "orders": orders, "revenue": revenue, "total_dep": total_dep}

def get_today_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    orders   = conn.execute("SELECT COUNT(*) as n FROM orders WHERE created_at LIKE ? AND refunded=0", (f"{today}%",)).fetchone()["n"]
    revenue  = conn.execute("SELECT COALESCE(SUM(amount_usdt),0) as s FROM orders WHERE created_at LIKE ? AND refunded=0", (f"{today}%",)).fetchone()["s"]
    dep_cnt  = conn.execute("SELECT COUNT(*) as n FROM deposit_requests WHERE credited_at LIKE ?", (f"{today}%",)).fetchone()["n"]
    dep_amt  = conn.execute("SELECT COALESCE(SUM(requested_usdt),0) as s FROM deposit_requests WHERE credited_at LIKE ?", (f"{today}%",)).fetchone()["s"]
    conn.close()
    return {"ord_count": orders, "ord_amount": revenue, "dep_count": dep_cnt, "dep_amount": dep_amt}

def get_daily_report(date_str: str):
    """
    Full admin daily report for an arbitrary date (YYYY-MM-DD):
    orders placed that day, deposits completed that day, and a wallet-balance
    snapshot (current, not historical — SQLite doesn't keep balance history).
    """
    conn = get_conn()
    ord_row = conn.execute(
        "SELECT COUNT(*) as n, COALESCE(SUM(amount_usdt),0) as s "
        "FROM orders WHERE created_at LIKE ? AND refunded=0", (f"{date_str}%",)
    ).fetchone()
    dep_row = conn.execute(
        "SELECT COUNT(*) as n, COALESCE(SUM(requested_usdt),0) as s "
        "FROM deposit_requests WHERE status='completed' AND credited_at LIKE ?", (f"{date_str}%",)
    ).fetchone()
    dep_fail = conn.execute(
        "SELECT COUNT(*) as n FROM deposit_requests "
        "WHERE created_at LIKE ? AND status IN ('expired','cancelled')", (f"{date_str}%",)
    ).fetchone()
    new_users = conn.execute(
        "SELECT COUNT(*) as n FROM users WHERE joined_at LIKE ?", (f"{date_str}%",)
    ).fetchone()
    total_bal = conn.execute("SELECT COALESCE(SUM(balance),0) as s FROM users").fetchone()["s"]
    total_users = conn.execute("SELECT COUNT(*) as n FROM users").fetchone()["n"]
    orders = conn.execute(
        "SELECT o.*, u.username FROM orders o LEFT JOIN users u ON u.user_id=o.user_id "
        "WHERE o.created_at LIKE ? AND o.refunded=0 ORDER BY o.id DESC", (f"{date_str}%",)
    ).fetchall()
    deposits = conn.execute(
        "SELECT dr.*, u.username FROM deposit_requests dr LEFT JOIN users u ON u.user_id=dr.user_id "
        "WHERE dr.status='completed' AND dr.credited_at LIKE ? ORDER BY dr.id DESC", (f"{date_str}%",)
    ).fetchall()
    conn.close()
    return {
        "date": date_str,
        "ord_count": ord_row["n"], "ord_amount": ord_row["s"],
        "dep_count": dep_row["n"], "dep_amount": dep_row["s"],
        "dep_failed": dep_fail["n"], "new_users": new_users["n"],
        "total_balance_now": total_bal, "total_users_now": total_users,
        "orders": [dict(r) for r in orders], "deposits": [dict(r) for r in deposits],
    }

# ── Admins ────────────────────────────────────────────────────────────────────

def get_extra_admins():
    conn = get_conn()
    rows = conn.execute("SELECT user_id FROM extra_admins").fetchall()
    conn.close()
    return [r["user_id"] for r in rows]

def add_extra_admin(user_id):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO extra_admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def remove_extra_admin(user_id):
    conn = get_conn()
    conn.execute("DELETE FROM extra_admins WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# ── Support Tickets ───────────────────────────────────────────────────────────

def create_ticket(user_id, subject):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("INSERT INTO support_tickets (user_id,subject,created_at,updated_at) VALUES (?,?,?,?)",
              (user_id, subject, now, now))
    tid = c.lastrowid
    conn.commit()
    conn.close()
    return tid

def get_ticket(tid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM support_tickets WHERE id=?", (tid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_tickets(user_id):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM support_tickets WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_open_tickets():
    conn = get_conn()
    rows = conn.execute(
        "SELECT t.*, u.username, u.full_name FROM support_tickets t LEFT JOIN users u ON u.user_id=t.user_id "
        "WHERE t.status='open' ORDER BY t.id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_ticket_message(ticket_id, sender_id, message, is_admin=False):
    conn = get_conn()
    conn.execute(
        "INSERT INTO ticket_messages (ticket_id,sender_id,is_admin,message,sent_at) VALUES (?,?,?,?,?)",
        (ticket_id, sender_id, 1 if is_admin else 0, message, datetime.now().isoformat())
    )
    conn.execute("UPDATE support_tickets SET updated_at=? WHERE id=?", (datetime.now().isoformat(), ticket_id))
    conn.commit()
    conn.close()

def get_ticket_messages(ticket_id):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id", (ticket_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def close_ticket(tid):
    conn = get_conn()
    conn.execute("UPDATE support_tickets SET status='closed', updated_at=? WHERE id=?",
                 (datetime.now().isoformat(), tid))
    conn.commit()
    conn.close()

# ── Referrals ─────────────────────────────────────────────────────────────────

def get_user_by_referral_code(code):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE referral_code=?", (code,)).fetchone()
    conn.close()
    return dict(row) if row else None

def set_referred_by(user_id, referrer_id):
    conn = get_conn()
    conn.execute("UPDATE users SET referred_by=? WHERE user_id=? AND referred_by IS NULL",
                 (referrer_id, user_id))
    conn.execute("INSERT OR IGNORE INTO referrals (referrer_id,referred_id,created_at) VALUES (?,?,?)",
                 (referrer_id, user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_referral_count(user_id):
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) as n FROM referrals WHERE referrer_id=?", (user_id,)).fetchone()["n"]
    conn.close()
    return n

def credit_referral_deposit_bonus(user_id, amount):
    """Give the referrer a flat REFERRAL_BONUS_USDT bonus when their referred
    friend makes a qualifying deposit. Returns (referrer_id, bonus_amount) or (None, 0).

    NOTE: this used to be computed as `amount * config.REFERRAL_BONUS_USDT`,
    which — because REFERRAL_BONUS_USDT is 0.5 — paid the referrer 50% of
    every referred deposit instead of the flat 0.5 USDT advertised to users
    in the "Refer & Earn" screen. That was a balance-inflation bug; fixed to
    pay the flat, advertised amount instead.
    """
    import config
    conn = get_conn()
    user = conn.execute("SELECT referred_by FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not user or not user["referred_by"]:
        conn.close()
        return None, 0
    ref_id = user["referred_by"]
    bonus = round(config.REFERRAL_BONUS_USDT, 6) if amount >= 1 else 0
    if bonus > 0:
        conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (bonus, ref_id))
        conn.execute("UPDATE referrals SET bonus_paid=bonus_paid+? WHERE referrer_id=? AND referred_id=?",
                     (bonus, ref_id, user_id))
        conn.commit()
    conn.close()
    return ref_id, bonus

def promote_vip(user_id):
    import config
    ref_count = get_referral_count(user_id)
    if ref_count >= config.VIP_REFERRALS_NEEDED:
        conn = get_conn()
        cnt = conn.execute("SELECT COUNT(*) as n FROM users WHERE is_vip=1").fetchone()["n"]
        if cnt < config.MAX_VIP_MEMBERS:
            conn.execute("UPDATE users SET is_vip=1 WHERE user_id=?", (user_id,))
            conn.commit()
        conn.close()

# ── Coupons ───────────────────────────────────────────────────────────────────

def get_coupons():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM coupons ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_coupon(code, discount, max_uses):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO coupons (code,discount,max_uses,created_at) VALUES (?,?,?,?)",
                 (code.upper(), discount, max_uses, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def toggle_coupon(cid):
    conn = get_conn()
    conn.execute("UPDATE coupons SET is_active=1-is_active WHERE id=?", (cid,))
    conn.commit()
    conn.close()

def delete_coupon(cid):
    conn = get_conn()
    conn.execute("DELETE FROM coupons WHERE id=?", (cid,))
    conn.commit()
    conn.close()

def validate_coupon(code, user_id):
    conn = get_conn()
    c = conn.execute("SELECT * FROM coupons WHERE code=? AND is_active=1", (code.upper(),)).fetchone()
    if not c: conn.close(); return None, "not_found"
    c = dict(c)
    if c["used_count"] >= c["max_uses"]: conn.close(); return None, "exhausted"
    used = conn.execute("SELECT 1 FROM coupon_uses WHERE coupon_id=? AND user_id=?", (c["id"], user_id)).fetchone()
    if used: conn.close(); return None, "already_used"
    conn.close()
    return c, "ok"

def apply_coupon(coupon_id, user_id):
    conn = get_conn()
    conn.execute("UPDATE coupons SET used_count=used_count+1 WHERE id=?", (coupon_id,))
    conn.execute("INSERT OR IGNORE INTO coupon_uses (coupon_id,user_id,used_at) VALUES (?,?,?)",
                 (coupon_id, user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ── Cart ──────────────────────────────────────────────────────────────────────

def add_to_cart(user_id, product_id, qty=1):
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("SELECT * FROM cart_items WHERE user_id=? AND product_id=?", (user_id, product_id)).fetchone()
    now = datetime.now().isoformat()
    if row:
        c.execute("UPDATE cart_items SET quantity=quantity+? WHERE id=?", (qty, row["id"]))
    else:
        c.execute("INSERT INTO cart_items (user_id,product_id,quantity,added_at) VALUES (?,?,?,?)", (user_id, product_id, qty, now))
    conn.commit()
    conn.close()

def get_cart(user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT ci.id as cart_id, ci.product_id, ci.quantity, p.name, p.emoji, "
        "p.price_usdt, p.category_id, p.is_active "
        "FROM cart_items ci JOIN products p ON p.id=ci.product_id "
        "WHERE ci.user_id=? ORDER BY ci.id", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_cart_item(user_id, product_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM cart_items WHERE user_id=? AND product_id=?", (user_id, product_id)).fetchone()
    conn.close()
    return dict(row) if row else None

def set_cart_qty(user_id, product_id, qty):
    conn = get_conn()
    if qty <= 0:
        conn.execute("DELETE FROM cart_items WHERE user_id=? AND product_id=?", (user_id, product_id))
    else:
        conn.execute("UPDATE cart_items SET quantity=? WHERE user_id=? AND product_id=?", (qty, user_id, product_id))
    conn.commit()
    conn.close()

def remove_cart_item(user_id, product_id):
    conn = get_conn()
    conn.execute("DELETE FROM cart_items WHERE user_id=? AND product_id=?", (user_id, product_id))
    conn.commit()
    conn.close()

def clear_cart(user_id):
    conn = get_conn()
    conn.execute("DELETE FROM cart_items WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# ── Resellers ─────────────────────────────────────────────────────────────────

def is_reseller(user_id):
    conn = get_conn()
    row = conn.execute("SELECT approved FROM resellers WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row and row["approved"] == 1

def add_reseller(user_id):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO resellers (user_id,approved,created_at) VALUES (?,0,?)",
                 (user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def approve_reseller(user_id):
    conn = get_conn()
    conn.execute("UPDATE resellers SET approved=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def revoke_reseller(user_id):
    conn = get_conn()
    conn.execute("DELETE FROM resellers WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_resellers():
    conn = get_conn()
    rows = conn.execute(
        "SELECT r.*, u.username, u.full_name FROM resellers r LEFT JOIN users u ON u.user_id=r.user_id "
        "WHERE r.approved=1"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_reseller_earning(reseller_id, order_id, gross_margin, owner_cut, reseller_cut):
    import config
    delay = get_setting_int("reseller_credit_delay_hours", config.RESELLER_CREDIT_DELAY_HOURS)
    now = datetime.now()
    available_at = (now + timedelta(hours=delay)).isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO reseller_earnings (reseller_id,order_id,gross_margin,owner_cut,reseller_cut,created_at,available_at) VALUES (?,?,?,?,?,?,?)",
        (reseller_id, order_id, gross_margin, owner_cut, reseller_cut, now.isoformat(), available_at)
    )
    conn.commit()
    conn.close()
    return reseller_cut, owner_cut

def mature_reseller_earnings():
    conn = get_conn()
    now = datetime.now().isoformat()
    rows = conn.execute("SELECT * FROM reseller_earnings WHERE status='pending' AND available_at<=?", (now,)).fetchall()
    if rows:
        conn.execute("UPDATE reseller_earnings SET status='available' WHERE status='pending' AND available_at<=?", (now,))
        conn.commit()
    conn.close()
    return [dict(r) for r in rows]

def get_reseller_balance_summary(reseller_id):
    conn = get_conn()
    pending   = conn.execute("SELECT COALESCE(SUM(reseller_cut),0) as s FROM reseller_earnings WHERE reseller_id=? AND status='pending'",   (reseller_id,)).fetchone()["s"]
    available = conn.execute("SELECT COALESCE(SUM(reseller_cut),0) as s FROM reseller_earnings WHERE reseller_id=? AND status='available'", (reseller_id,)).fetchone()["s"]
    withdrawn = conn.execute("SELECT COALESCE(SUM(reseller_cut),0) as s FROM reseller_earnings WHERE reseller_id=? AND status='withdrawn'", (reseller_id,)).fetchone()["s"]
    conn.close()
    return {"pending": pending, "available": available, "withdrawn": withdrawn}

def create_withdraw_request(user_id, amount):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO withdraw_requests (user_id,amount,requested_at) VALUES (?,?,?)",
              (user_id, amount, datetime.now().isoformat()))
    wid = c.lastrowid
    conn.commit()
    conn.close()
    return wid

def get_pending_withdraw_requests():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM withdraw_requests WHERE status='pending' ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_withdraw_request(wid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM withdraw_requests WHERE id=?", (wid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def mark_withdraw_earnings_consumed(reseller_id, amount):
    conn = get_conn()
    c = conn.cursor()
    rows = c.execute("SELECT * FROM reseller_earnings WHERE reseller_id=? AND status='available' ORDER BY id", (reseller_id,)).fetchall()
    remaining = amount
    for r in rows:
        if remaining <= 0: break
        c.execute("UPDATE reseller_earnings SET status='withdrawn' WHERE id=?", (r["id"],))
        remaining -= r["reseller_cut"]
    conn.commit()
    conn.close()

def process_withdraw_request(wid, approve):
    conn = get_conn()
    req = conn.execute("SELECT * FROM withdraw_requests WHERE id=?", (wid,)).fetchone()
    if not req: conn.close(); return None
    status = "paid" if approve else "rejected"
    conn.execute("UPDATE withdraw_requests SET status=?, processed_at=? WHERE id=?",
                 (status, datetime.now().isoformat(), wid))
    conn.commit()
    conn.close()
    if approve:
        mark_withdraw_earnings_consumed(req["user_id"], req["amount"])
    return dict(req)

# ── Advanced Admin Queries ─────────────────────────────────────────────────────

def get_today_deposits_all():
    """All deposits created today regardless of status (success + failed + pending)."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn  = get_conn()
    rows  = conn.execute(
        "SELECT dr.*, u.username, u.full_name FROM deposit_requests dr "
        "LEFT JOIN users u ON u.user_id=dr.user_id "
        "WHERE dr.created_at LIKE ? ORDER BY dr.id DESC", (f"{today}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_today_deposit_stats():
    """Today counts: success (count+sum), failed (expired+cancelled), pending."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn  = get_conn()
    ok  = conn.execute(
        "SELECT COUNT(*) as n, COALESCE(SUM(requested_usdt),0) as s "
        "FROM deposit_requests WHERE created_at LIKE ? AND status='completed'", (f"{today}%",)
    ).fetchone()
    fail = conn.execute(
        "SELECT COUNT(*) as n FROM deposit_requests "
        "WHERE created_at LIKE ? AND status IN ('expired','cancelled')", (f"{today}%",)
    ).fetchone()
    pend = conn.execute(
        "SELECT COUNT(*) as n FROM deposit_requests "
        "WHERE created_at LIKE ? AND status='pending'", (f"{today}%",)
    ).fetchone()
    conn.close()
    return {"success_count": ok["n"], "success_amt": ok["s"],
            "failed_count": fail["n"], "pending_count": pend["n"]}

def get_all_deposits_list(limit=50000):
    """All deposits ever, all statuses."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT dr.*, u.username, u.full_name FROM deposit_requests dr "
        "LEFT JOIN users u ON u.user_id=dr.user_id "
        "ORDER BY dr.id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_time_deposit_stats():
    conn = get_conn()
    ok   = conn.execute("SELECT COUNT(*) as n, COALESCE(SUM(requested_usdt),0) as s FROM deposit_requests WHERE status='completed'").fetchone()
    fail = conn.execute("SELECT COUNT(*) as n FROM deposit_requests WHERE status IN ('expired','cancelled')").fetchone()
    pend = conn.execute("SELECT COUNT(*) as n FROM deposit_requests WHERE status='pending'").fetchone()
    conn.close()
    return {"success_count": ok["n"], "success_amt": ok["s"],
            "failed_count": fail["n"], "pending_count": pend["n"]}

def get_user_full_history(user_id):
    """All deposits + orders for a user, newest first."""
    conn = get_conn()
    deps = conn.execute(
        "SELECT 'deposit' as type, id, created_at, requested_usdt as amount, "
        "network as extra, status, '' as product_name "
        "FROM deposit_requests WHERE user_id=? ORDER BY id DESC", (user_id,)
    ).fetchall()
    ords = conn.execute(
        "SELECT 'order' as type, id, created_at, amount_usdt as amount, "
        "'' as extra, status, product_name "
        "FROM orders WHERE user_id=? ORDER BY id DESC", (user_id,)
    ).fetchall()
    conn.close()
    merged = [dict(r) for r in deps] + [dict(r) for r in ords]
    merged.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return merged

def manual_credit_deposit(user_id, amount, txid="MANUAL", network="MANUAL"):
    """Admin manually credits a deposit to a user."""
    conn = get_conn()
    now  = datetime.now().isoformat()
    c    = conn.cursor()
    c.execute(
        "INSERT INTO deposit_requests "
        "(user_id,requested_usdt,expected_usdt,network,status,binance_txid,credited_at,created_at,expires_at) "
        "VALUES (?,?,?,?,'completed',?,?,?,?)",
        (user_id, amount, amount, network, txid, now, now, now)
    )
    did = c.lastrowid
    conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()
    return did

def get_all_tickets():
    """All tickets (open + closed), newest first."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT t.*, u.username, u.full_name FROM support_tickets t "
        "LEFT JOIN users u ON u.user_id=t.user_id ORDER BY t.id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Refund Requests (user-initiated) ─────────────────────────────────────────

def create_refund_request(user_id: int, order_id: int, reason: str) -> int:
    """Create a new user-initiated refund request. Returns request id."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO refund_requests (user_id, order_id, reason, status, created_at) "
        "VALUES (?, ?, ?, 'pending', ?)",
        (user_id, order_id, reason, datetime.now().isoformat())
    )
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return rid

def get_refund_request(rid: int):
    """Get a single refund request by id."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM refund_requests WHERE id=?", (rid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_refund_request_for_order(user_id: int, order_id: int):
    """Check if user already has a pending/approved refund request for this order."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM refund_requests WHERE user_id=? AND order_id=? AND status IN ('pending','approved') ORDER BY id DESC LIMIT 1",
        (user_id, order_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def get_pending_refund_requests():
    """Get all pending refund requests for admin review."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT rr.*, u.username, u.full_name, o.product_name, o.amount_usdt "
        "FROM refund_requests rr "
        "LEFT JOIN users u ON u.user_id = rr.user_id "
        "LEFT JOIN orders o ON o.id = rr.order_id "
        "WHERE rr.status='pending' ORDER BY rr.id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def approve_refund_request(rid: int):
    """Mark request as approved and perform balance refund. Returns (request_dict, order_dict) or (None, None)."""
    conn = get_conn()
    req = conn.execute("SELECT * FROM refund_requests WHERE id=?", (rid,)).fetchone()
    if not req or req["status"] != "pending":
        conn.close()
        return None, None
    order = conn.execute("SELECT * FROM orders WHERE id=?", (req["order_id"],)).fetchone()
    if not order:
        conn.close()
        return None, None
    # Update refund request status
    conn.execute(
        "UPDATE refund_requests SET status='approved', resolved_at=? WHERE id=?",
        (datetime.now().isoformat(), rid)
    )
    # Refund the order (mark refunded + credit balance)
    if not order["refunded"]:
        conn.execute("UPDATE orders SET refunded=1 WHERE id=?", (order["id"],))
        conn.execute(
            "UPDATE users SET balance=balance+?, total_spent_usdt=total_spent_usdt-? WHERE user_id=?",
            (order["amount_usdt"], order["amount_usdt"], order["user_id"])
        )
        if order["stock_item_id"]:
            conn.execute(
                "UPDATE stock_items SET is_sold=0, sold_to=NULL, order_id=NULL, sold_at=NULL WHERE id=?",
                (order["stock_item_id"],)
            )
            refresh_stock_count_conn(conn, order["product_id"])
    conn.commit()
    conn.close()
    return dict(req), dict(order)

def reject_refund_request(rid: int, admin_note: str = ""):
    """Mark request as rejected. Returns request_dict or None."""
    conn = get_conn()
    req = conn.execute("SELECT * FROM refund_requests WHERE id=?", (rid,)).fetchone()
    if not req or req["status"] != "pending":
        conn.close()
        return None
    conn.execute(
        "UPDATE refund_requests SET status='rejected', admin_note=?, resolved_at=? WHERE id=?",
        (admin_note, datetime.now().isoformat(), rid)
    )
    conn.commit()
    conn.close()
    return dict(req)

# ── Refund detail + chat (used by web admin panel) ────────────────────────────

def get_refund_request_full(rid: int):
    """Full refund request detail: user, order, product, credential, chat."""
    conn = get_conn()
    req = conn.execute("SELECT * FROM refund_requests WHERE id=?", (rid,)).fetchone()
    if not req:
        conn.close()
        return None
    req = dict(req)
    order = conn.execute("SELECT * FROM orders WHERE id=?", (req["order_id"],)).fetchone()
    user  = conn.execute("SELECT * FROM users WHERE user_id=?", (req["user_id"],)).fetchone()
    stock = conn.execute("SELECT data FROM stock_items WHERE order_id=?", (req["order_id"],)).fetchone()
    conn.close()
    req["order"]      = dict(order) if order else None
    req["user"]       = dict(user) if user else None
    req["credential"] = stock["data"] if stock else ""
    return req

def get_all_refund_requests(limit=1000):
    """All refund requests (any status), most recent first, with user/order joined."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT rr.*, u.username as username, u.full_name as full_name, "
        "o.product_name as product_name, o.amount_usdt as amount_usdt "
        "FROM refund_requests rr "
        "LEFT JOIN users u ON u.user_id = rr.user_id "
        "LEFT JOIN orders o ON o.id = rr.order_id "
        "ORDER BY rr.id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_refund_message(refund_id: int, sender_id: int, message: str, is_admin: bool = False):
    conn = get_conn()
    conn.execute(
        "INSERT INTO refund_messages (refund_id, sender_id, is_admin, message, sent_at) VALUES (?,?,?,?,?)",
        (refund_id, sender_id, 1 if is_admin else 0, message, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_refund_messages(refund_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM refund_messages WHERE refund_id=? ORDER BY id ASC", (refund_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Web admin panel login ──────────────────────────────────────────────────────

def get_web_admin(username: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM web_admins WHERE username=?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_web_admin(username: str, password_hash: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO web_admins (id, username, password_hash, created_at) "
        "VALUES ((SELECT id FROM web_admins WHERE username=?), ?, ?, ?)",
        (username, username, password_hash, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

# ── Restock requests (users who tapped "Request Restock") ──────────────────

def add_restock_request(product_id: int, user_id: int):
    conn = get_conn()
    # avoid duplicate un-notified requests for the same user+product
    existing = conn.execute(
        "SELECT id FROM restock_requests WHERE product_id=? AND user_id=? AND notified=0",
        (product_id, user_id)
    ).fetchone()
    if existing:
        conn.close()
        return
    conn.execute(
        "INSERT INTO restock_requests (product_id, user_id, notified, created_at) VALUES (?,?,0,?)",
        (product_id, user_id, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_pending_restock_requesters(product_id: int):
    """User IDs who asked to be notified when this product is back in stock."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT user_id FROM restock_requests WHERE product_id=? AND notified=0",
        (product_id,)
    ).fetchall()
    conn.close()
    return [r["user_id"] for r in rows]

def mark_restock_notified(product_id: int):
    conn = get_conn()
    conn.execute("UPDATE restock_requests SET notified=1 WHERE product_id=? AND notified=0", (product_id,))
    conn.commit()
    conn.close()

def mark_restock_request_notified(product_id: int, user_id: int):
    """Mark one user's restock request after a successful Telegram DM."""
    conn = get_conn()
    conn.execute(
        "UPDATE restock_requests SET notified=1 "
        "WHERE product_id=? AND user_id=? AND notified=0",
        (product_id, user_id),
    )
    conn.commit()
    conn.close()

def claim_low_stock_alert(product_id: int, stock_count: int, threshold: int) -> bool:
    """Return True only when the product newly enters the low-stock range.

    The alert is edge-triggered: users get one broadcast when stock goes below
    the threshold, not one DM for every subsequent purchase.  Restocking back
    to the threshold or above arms the next alert.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT low_stock_alert_sent FROM products WHERE id=?", (product_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    sent = bool(row["low_stock_alert_sent"] or 0)
    is_low = int(stock_count) > 0 and int(stock_count) < int(threshold)
    if is_low and not sent:
        conn.execute(
            "UPDATE products SET low_stock_alert_sent=1 WHERE id=?", (product_id,)
        )
        conn.commit()
        conn.close()
        return True
    if not is_low and sent:
        conn.execute(
            "UPDATE products SET low_stock_alert_sent=0 WHERE id=?", (product_id,)
        )
        conn.commit()
    else:
        conn.close()
    return False


# Runtime storage is MongoDB.  Keep this legacy module as the stable import
# path for the bot and web panel, but override its SQLite implementations with
# the Mongo-compatible API after the historical code has been loaded.
from mongo_database import *  # noqa: F401,F403,E402
