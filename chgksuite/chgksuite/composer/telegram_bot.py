import asyncio
import json
import os
import sqlite3
import threading
from datetime import datetime

import requests
import toml
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from chgksuite.common import ChgksuiteError, get_chgksuite_dir


class TelegramSidecarBot:
    def __init__(self, bot_token, db_path):
        self.db_path = db_path
        self._local = threading.local()
        self.token = bot_token
        self.loop = None
        self.application = None
        self._started = threading.Event()

    @property
    def conn(self):
        if not hasattr(self._local, "connection"):
            self._local.connection = sqlite3.connect(self.db_path)
        return self._local.connection

    async def handle_message(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        message = update.message or update.channel_post
        if message is None:
            return
        cursor = self.conn.cursor()
        raw_data = json.dumps(update.to_dict(), ensure_ascii=False)
        cursor.execute(
            "INSERT INTO messages (raw_data, chat_id, created_at) VALUES (?, ?, ?)",
            (raw_data, message.chat.id, datetime.now().astimezone().isoformat()),
        )
        self.conn.commit()

    async def error_handler(self, update, context):
        print(f"Update {update} caused error: {context.error}")

    async def check_connectivity(self):
        url = f"https://api.telegram.org/bot{self.token}/getMe"
        req = await asyncio.to_thread(requests.get, url)
        cursor = self.conn.cursor()
        if req.status_code == 200 and "ok" in req.json():
            cursor.execute(
                "INSERT INTO bot_status (raw_data, created_at) VALUES (?, ?)",
                (json.dumps({"status": "ok"}), datetime.now().astimezone().isoformat()),
            )
            self.conn.commit()
        else:
            print(f"couldn't check status, req: {req.text}")
            cursor.execute(
                "INSERT INTO bot_status (raw_data, created_at) VALUES (?, ?)",
                (
                    json.dumps(
                        {
                            "status": "bad",
                            "error": req.text,
                            "status_code": req.status_code,
                        }
                    ),
                    datetime.now().astimezone().isoformat(),
                ),
            )
            self.conn.commit()
        return True

    def run(self):
        loop = asyncio.get_event_loop()
        self.loop = loop
        application = (
            Application.builder()
            .token(self.token)
            .connect_timeout(300.0)
            .read_timeout(300.0)
            .write_timeout(300.0)
            .build()
        )
        self.application = application
        application.add_handler(MessageHandler(filters.ALL, self.handle_message))
        application.add_error_handler(self.error_handler)
        loop.run_until_complete(application.initialize())
        loop.run_until_complete(application.start())
        loop.run_until_complete(
            application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES, drop_pending_updates=True
            )
        )
        self._started.set()
        loop.run_forever()
        # run_forever() returns once stop() schedules loop.stop(); tear the bot
        # down on this same thread/loop so the getUpdates poller is released.
        try:
            if application.updater.running:
                loop.run_until_complete(application.updater.stop())
            if application.running:
                loop.run_until_complete(application.stop())
            loop.run_until_complete(application.shutdown())
        finally:
            loop.close()

    def stop(self):
        """Stop polling and shut the bot down from another thread."""
        self._started.wait(timeout=30)
        loop = self.loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)


def run_bot_in_thread(bot_token, db_path):
    """Run the bot in a daemon thread.

    Returns (thread, bot). Call ``bot.stop()`` then ``thread.join()`` to release
    the getUpdates poller; otherwise a second poller on the same token will raise
    ``telegram.error.Conflict``.
    """

    bot = TelegramSidecarBot(bot_token, db_path)

    def thread_function():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        connectivity_ok = loop.run_until_complete(bot.check_connectivity())
        if not connectivity_ok:
            raise ChgksuiteError("bot couldn't connect")
        bot.run()

    bot_thread = threading.Thread(target=thread_function, daemon=True)
    bot_thread.start()
    return bot_thread, bot


def main():
    toml_path = os.path.join(get_chgksuite_dir(), "telegram.toml")
    with open(toml_path, "r", encoding="utf8") as f:
        bot_token = toml.load(f)["bot_token"]
    run_bot_in_thread(bot_token, "test_bot.db")


if __name__ == "__main__":
    main()
