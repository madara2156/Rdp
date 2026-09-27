# BASS TG STORE — Bot + Web Admin Panel (Render 24/7 deploy)

This package runs **two things in one process** so it fits Render's free
web-service tier (which only allows one exposed port):

1. **The Telegram bot** — unchanged, still `bot.py`, running in a background thread.
2. **A web admin panel** (Flask) at your Render URL — a full mirror of the bot's
   `/admin` panel, protected by a username + password login.

A built-in **self-ping** thread hits your own `/ping` route every 2 minutes so
the free instance doesn't spin down from inactivity.

---

## 1. Deploy to Render

1. Push this folder to a GitHub repo.
2. On [render.com](https://render.com) → **New → Web Service** → connect the repo.
   (Render will auto-detect `render.yaml` — or set these manually:)
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python run.py`
   - **Plan:** Free
3. Add these **Environment Variables** (Render → your service → Environment):

   | Key | Value |
   |---|---|
   | `BOT_TOKEN` | your bot token from @BotFather |
   | `ADMIN_IDS` | your Telegram user ID (comma-separated if more than one) |
   | `WEB_ADMIN_USERNAME` | username you'll use to log into the web panel |
   | `WEB_ADMIN_PASSWORD` | a strong password for the web panel |
   | `FLASK_SECRET_KEY` | any long random string (Render can auto-generate this) |
   | `USDT_TRC20_ADDRESS` | your TRC20 wallet address *(optional — can set later in Settings)* |
   | `USDT_BEP20_ADDRESS` | your BEP20 wallet address *(optional)* |
   | `BINANCE_PAY_ID` | your Binance Pay ID *(optional)* |
   | `ZAPUPI_API_KEY` | ZapUPI live API key from ZapUPI Dashboard → API Keys |
   | `ZAPUPI_INR_PER_USDT` | INR conversion rate used for wallet credit, e.g. `90` |
   | `ZAPUPI_MIN_INR` | minimum UPI payment in INR, e.g. `90` |
   | `ZAPUPI_WEBHOOK_URL` | optional full URL, e.g. `https://your-app.onrender.com/webhooks/zapupi`; otherwise Render URL + `/webhooks/zapupi` is auto-detected |
   | `BOT_USERNAME` | main store bot username, without `@`, for Buy Item links |
    | `MONGODB_URI` | MongoDB Atlas connection string *(required)* |
    | `MONGODB_DB` | MongoDB database name (default: `godmadara01`) |

   Do **not** put `BOT_TOKEN` or passwords directly in code or in `.env` committed
   to git — always use Render's Environment tab.

4. Deploy. Render gives you a URL like `https://bass-tg-store.onrender.com`.
   - Open it → you'll see the **login page**.
   - Log in with `WEB_ADMIN_USERNAME` / `WEB_ADMIN_PASSWORD`.
   - The Telegram bot starts automatically in the background — no extra step.

That's it — the bot and the web panel are now both live 24/7 on the same
free Render service, and `/ping` gets hit every 2 minutes automatically so
 it won't sleep.

### ZapUPI verification checklist

The bot creates orders through ZapUPI's backend API, sends the per-order
`webhook_url`, acknowledges callbacks with HTTP 200, and confirms the order
again through `order-status` before crediting a wallet. Keep the webhook URL
publicly reachable over HTTPS; do not point it at the Telegram bot URL or an
admin-only route.

For a local code check, run:

```bash
python tests/test_zapupi.py
```

### MongoDB storage

This build does not use a Render persistent disk. Normal shop data, TG Store
orders, OTP stock, Telegram `StringSession` values, wallets, deposits, and
admin data are stored in MongoDB. The first deployment starts with the MongoDB
database as its source of truth; the old local SQLite database is not imported
automatically. Legacy OTP stock records that only contain `session_file` still
need their original files until they are re-uploaded through the admin panel.

---

## 2. What the web panel can do

Every feature from the Telegram `/admin` panel is mirrored here, reading and
writing the **same database**, so changes made on the web show up instantly
in the bot and vice versa:

- Dashboard (today + all-time stats)
- Orders (today / all, with full date & time)
- Deposits (today / pending / all) — approve or reject pending ones
- Manual Deposit, Gift Balance
- **Refund Requests** — open a request to see the full order, the exact
  item/credential (ID + password) that was delivered, the user's reason,
  and a live chat thread with the user — then Approve or Reject
- Coupons, Categories, Products, Stock (add/view/clear), Free Items
- Users (search, ban/unban, adjust balance), full per-user history
- Tickets (reply, close)
- Admins (add/remove extra admins)
- Broadcast to all users
- Daily History (last 14 days)
- Settings — bot name/emoji, TRC20/BEP20/Binance Pay addresses,
  ZapUPI INR rate/minimum/webhook URL, min deposit, low-stock threshold,
  maintenance mode, referral toggle, force-join channels (up to 5)
- **TG Panel** — the Telegram Account / OTP admin section is now also available
  on the web: add StringSession or ZIP stock, manage availability by country,
  auto-price rules, session health checks and dead-session cleanup, OTP stats,
  2FA updates, session storage overview, the USDT⇄INR rate, and the same
  **phone → Telegram OTP → 2FA → save account** login flow as the bot panel.

The web ZIP importer detects authorized sessions, country and account year and
uses the same `otp_stock` records as the Telegram panel. If an account has 2FA,
provide its password in the importer field; Telegram does not expose existing
2FA passwords to the application. Session strings are accepted for manual
imports and are never rendered back in the UI.

---

## 3. Local testing (optional)

```bash
pip install -r requirements.txt
export BOT_TOKEN=xxx
export ADMIN_IDS=your_telegram_id
export WEB_ADMIN_USERNAME=admin
export WEB_ADMIN_PASSWORD=test1234
export FLASK_SECRET_KEY=any-string
python run.py
```

Then open `http://localhost:10000`.

---

## 4. Notes & security

- The web admin login is completely separate from Telegram admin IDs — it's
  its own username/password stored (hashed) in the database.
- Change `WEB_ADMIN_PASSWORD` to something strong before going live.
- If you ever suspect your `BOT_TOKEN` was exposed, revoke and regenerate it
  via **@BotFather → /revoke** immediately, then update the Render env var.
- `run.py` restarts the bot's polling loop automatically if it ever crashes,
  so a temporary network blip won't take the bot down.
