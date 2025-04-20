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

from chgksuite.common import get_chgksuite_dir


class TelegramSidecarBot:
    def __init__(self, bot_token, db_path):
        self.db_path = db_path
        self._local = threading.local()
        self.token = bot_token

    @property
    def conn(self):
        if not hasattr(self._local, "connection"):
            self._local.connection = sqlite3.connect(self.db_path)
        return self._local.connection

    async def handle_message(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        cursor = self.conn.cursor()
        raw_data = json.dumps(update.to_dict(), ensure_ascii=False)
        cursor.execute(
            "INSERT INTO messages (raw_data, chat_id, created_at) VALUES (?, ?, ?)",
            (raw_data, update.message.chat.id, datetime.now().isoformat()),
        )
        self.conn.commit()

    async def error_handler(self, update, context):
        print(f"Update {update} caused error: {context.error}")

    async def check_connectivity(self):
        url = f"https://api.telegram.org/bot{self.token}/getMe"
        req = requests.get(url)
        cursor = self.conn.cursor()
        if req.status_code == 200 and "ok" in req.json():
            cursor.execute(
                "INSERT INTO bot_status (raw_data, created_at) VALUES (?, ?)",
                (json.dumps({"status": "ok"}), datetime.now().isoformat()),
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
                    datetime.now().isoformat(),
                ),
            )
            self.conn.commit()
        return True

    def run(self):
        loop = asyncio.get_event_loop()
        application = (
            Application.builder()
            .token(self.token)
            .connect_timeout(30.0)
            .read_timeout(30.0)
            .write_timeout(30.0)
            .build()
        )
        application.add_handler(MessageHandler(filters.ALL, self.handle_message))
        application.add_error_handler(self.error_handler)
        loop.run_until_complete(application.initialize())
        loop.run_until_complete(application.start())
        loop.run_until_complete(
            application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES, drop_pending_updates=True
            )
        )
        loop.run_forever()


def run_bot_in_thread(bot_token, db_path):
    """Run the bot in a daemon thread."""

    def thread_function():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bot = TelegramSidecarBot(bot_token, db_path)
        connectivity_ok = loop.run_until_complete(bot.check_connectivity())
        if not connectivity_ok:
            raise Exception("bot couldn't connect")
        bot.run()

    bot_thread = threading.Thread(target=thread_function, daemon=True)
    bot_thread.start()
    return bot_thread


def main():
    toml_path = os.path.join(get_chgksuite_dir(), "telegram.toml")
    with open(toml_path, "r", encoding="utf8") as f:
        bot_token = toml.load(f)["bot_token"]
    run_bot_in_thread(bot_token, "test_bot.db")


if __name__ == "__main__":
    main()
