# storebot
## TG Store (merged)

Telegram account selling (TG ACCOUNT BUY + admin TG Panel) is now part of this bot.

**User side** — Home menu → `TG ACCOUNT BUY`
- Country → year/price → Buy 1 or Buy Bulk (zip of sessions)
- Live OTP delivery, "Get OTP Again", "Finish & Logout"
- Pays from the same wallet balance (INR price converted via the USDT rate in TG Panel)
- Every sale is also logged into the normal `orders` history

**Admin side** — Admin Panel → `TG Panel`
- Add Stock (single phone / .zip bulk upload), Manage Stock per country
- Auto-Price per country+year, USDT rate, Test Sessions, Delete Dead
- OTP Stats (today / week / all time), 2FA Manager, Sessions Folder dump

**Setup**
1. `pip install -r requirements.txt` (adds telethon, pymongo, python-dotenv)
2. Set `MONGODB_URI` (and optionally `MONGODB_DB`) — TG store stock/orders/prices live there.
   The rest of the bot keeps using the existing SQLite file.
3. On Render, attach a persistent disk and point `OTP_SESSIONS_DIR` at it so
   uploaded `.session` files survive restarts.

## Shop stock notifications

- Whenever new stock is added, every registered user receives a private
  **BACK IN STOCK** DM with the product and a Buy button. No user-side
  **Request Restock** action is required.
- When stock drops below `LOW_STOCK_THRESHOLD` (default `5`), all registered
  users receive one low-stock DM with a Buy button. The alert is not repeated
  on every sale; it becomes available again after stock recovers to the
  threshold or above.

## Purchase log group

Add the bot to the group where you want sales notifications, then send:

```text
/set
```

The command must be sent by the store admin or a Telegram group
administrator. It binds that group persistently and sends safe notifications
for normal products, cart purchases, single TG/OTP accounts, and bulk TG
account purchases. Credentials, phone numbers, OTPs, and session files are
never included in the log. To disable the configured group, send `/unset`
from that group as an admin.

When the owner adds new OTT stock or TG account stock, the bot also broadcasts
a stock-available message to registered users and sends a separate stock-added
message to the configured log group. Stock credentials and session data are
not included in these announcements.

After a TG account buyer receives the first OTP, `Get OTP Again` checks for a
new Telegram code for 30 seconds. If Telegram does not send another code, the
bot safely shows the latest OTP already received for that same active order.
