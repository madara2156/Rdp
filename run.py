"""
run.py — single entrypoint for Render (or any host that only exposes ONE port).

Runs three things together:
  1. The Telegram bot (bot.py's build_app().run_polling()) in a background thread.
  2. The Flask web admin panel (webapp/app.py) on the main thread, bound to $PORT.
  3. A self-ping thread that hits this service's own /ping route every 2 minutes,
     so Render's free tier doesn't spin the instance down from inactivity.

Local development:
    python run.py
    → open http://localhost:10000  (or $PORT)

Render:
    Start Command:  python run.py
    (Render sets $PORT automatically; RENDER_EXTERNAL_URL is also auto-set.)
"""
import os
import sys
import time
import asyncio
import threading

import requests

import database as db
import bot as botmodule
from Webapp.app import create_app


def _validate_token_and_clear_webhook(token, label):
    """Quick synchronous sanity check before starting one polling bot:
       1. Confirms BOT_TOKEN actually works (calls getMe).
       2. Deletes any leftover webhook — if a webhook is set, run_polling()
          fails with a Conflict error forever without a clear reason."""
    base = f"https://api.telegram.org/bot{token}"
    try:
        me = requests.get(f"{base}/getMe", timeout=15).json()
        if not me.get("ok"):
            return False
    except Exception:
        return False

    try:
        wh = requests.get(f"{base}/deleteWebhook", params={"drop_pending_updates": True}, timeout=15).json()
    except Exception:
        pass
    return True


def run_bot():
    """Runs the Telegram bot's polling loop in this thread forever."""
    # This function runs in a background thread. Only the MAIN thread gets an
    # asyncio event loop automatically — python-telegram-bot's run_polling()
    # needs one to exist for *this* thread, so we create and register a fresh
    # one on every attempt (PTB closes the loop when polling stops/crashes).
    backoff = 10

    # Do not run this during the web-service bootstrap. MongoDB can take
    # several seconds to connect (or up to its selection timeout when the
    # URI/network is wrong), while Render is waiting for the HTTP port.
    # The web panel can still become healthy even if the optional OTP store
    # is temporarily unavailable.
    try:
        import otp_module
        otp_module.init_schema()
    except Exception:
        pass

    while True:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            if not _validate_token_and_clear_webhook(
                getattr(botmodule.config, "BOT_TOKEN", ""), "BOT_TOKEN"
            ):
                time.sleep(backoff)
                continue
            application = botmodule.build_app()
            # stop_signals=None → don't try to install OS signal handlers,
            # which only works on the main thread. This thread is a worker.
            application.run_polling(drop_pending_updates=True, stop_signals=None)
        except Exception:
            time.sleep(backoff)


def self_ping():
    """Pings this service's own /ping URL every 2 minutes to prevent the
    Render free-tier instance from going to sleep due to inactivity."""
    url = (
        os.environ.get("SELF_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or (f"https://{os.environ['RENDER_EXTERNAL_HOSTNAME']}" if os.environ.get("RENDER_EXTERNAL_HOSTNAME") else "")
    ).rstrip("/")
    if not url:
        return
    ping_url = f"{url}/ping"
    while True:
        time.sleep(120)
        try:
            requests.get(ping_url, timeout=15)
        except Exception:
            pass


def main():
    # Create the Flask app before starting Telegram polling. This initializes
    # the MongoDB indexes and lets us bind Render's PORT immediately, instead
    # of making Render wait for MongoDB/Telegram startup first.
    app = create_app()
    port = int(os.environ.get("PORT", 10000))

    if not getattr(botmodule.config, "BOT_TOKEN", ""):
        pass
    else:
        threading.Thread(target=run_bot, daemon=True, name="tg-bot").start()

    threading.Thread(target=self_ping, daemon=True, name="self-ping").start()

    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port)
    except ImportError:
        app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
