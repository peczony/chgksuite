from __future__ import annotations

import contextlib
import html
import json
import logging
import os
import random
import re
import sqlite3
import tempfile
import time
import urllib.parse
import uuid

import requests
import toml
from PIL import Image, ImageOps

from chgksuite.common import (
    HYPERLINK_SAFE_CHARS,
    ChgksuiteError,
    get_chgksuite_dir,
    init_logger,
    load_settings,
    save_pil_image_as_jpeg,
    tryint,
)
from chgksuite.composer.composer_common import BaseExporter, parseimg
from chgksuite.composer.telegram_bot import run_bot_in_thread

logger = logging.getLogger(__name__)


def get_saved_telegram_targets():
    """
    Load all saved channel/chat usernames from resolve.db.
    Returns a list of usernames that have been previously used.
    """
    chgksuite_dir = get_chgksuite_dir()
    resolve_db_path = os.path.join(chgksuite_dir, "resolve.db")

    if not os.path.exists(resolve_db_path):
        return []

    try:
        conn = sqlite3.connect(resolve_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM resolve ORDER BY username")
        results = cursor.fetchall()
        conn.close()
        return [row[0] for row in results]
    except Exception:
        logger.exception("could not list resolved usernames")
        return []


_TG_TAGS = (
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "tg-spoiler", "tg-emoji", "a", "code", "pre", "span", "blockquote",
)
_TG_TAG_RE = re.compile(
    r"</?(?:" + "|".join(_TG_TAGS) + r")(?:\s[^>]*)?>", re.IGNORECASE
)


def tg_len(html):
    """Return text length after stripping Telegram-supported HTML tags."""
    return len(_TG_TAG_RE.sub("", html))


# Telegram silently drops entities beyond this limit per message.
_TG_MAX_ENTITIES = 100

# Inline marker for an image embedded in rich message text.
_TG_IMG_SENTINEL_RE = re.compile("\x00img:([^\x00]+)\x00")

_TG_ENTITY_RE = re.compile(r"<(?:b|strong|i|em|u|s|a |code|pre)")


def tg_entity_count(html):
    """Estimate the number of Telegram entities in an HTML string."""
    return len(_TG_ENTITY_RE.findall(html))


def _format_html_hyperlink(url, disable_asterisks_processing=False):
    href = urllib.parse.quote(url, safe=HYPERLINK_SAFE_CHARS)
    href = html.escape(href, quote=True)
    text = html.escape(url, quote=False).replace("_", "&#95;")
    if not disable_asterisks_processing:
        text = text.replace("*", "&#42;")
    return f'<a href="{href}">{text}</a>'


def get_text(msg_data):
    if "message" in msg_data and "text" in msg_data["message"]:
        return msg_data["message"]["text"]


class TelegramExporter(BaseExporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chgksuite_dir = get_chgksuite_dir()
        self.logger = kwargs.get("logger") or init_logger("composer")
        self.qcount = 1
        self.number = 1
        self.tg_heading = None
        self.forwarded_message = None
        self.target_channel = None
        self.created_at = None
        self.telegram_toml_path = os.path.join(self.chgksuite_dir, "telegram.toml")
        self.resolve_db_path = os.path.join(self.chgksuite_dir, "resolve.db")
        self.temp_db_path = os.path.join(
            tempfile.gettempdir(), f"telegram_sidecar_{uuid.uuid4().hex}.db"
        )
        self.bot_token = None
        self.bot = None
        self.bot_thread = None
        self.control_chat_id = None  # Chat ID where the user talks to the bot
        self.channel_id = None  # Target channel ID
        self.chat_id = None  # Discussion group ID linked to the channel
        self.auth_uuid = uuid.uuid4().hex[:8]
        self.chat_auth_uuid = uuid.uuid4().hex[:8]
        self.session = requests.Session()
        self.si_mode = self.game in ("si", "troika")
        self.rich_mode = True
        self.init_telegram()

    def check_connectivity(self):
        result = self.send_api_request("getMe")
        if self.args.debug:
            print(f"connection successful! {result}")
        self.bot_id = result["id"]

    def init_temp_db(self):
        self.db_conn = sqlite3.connect(self.temp_db_path)
        self.db_conn.row_factory = sqlite3.Row

        cursor = self.db_conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            raw_data TEXT,
            chat_id TEXT,
            created_at TEXT
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_status (
            raw_data TEXT,
            created_at TEXT
        )
        """)

        self.db_conn.commit()

    def init_telegram(self):
        """Initialize Telegram API connection and start sidecar bot."""
        self.bot_token = self.get_api_credentials()
        assert self.bot_token is not None

        self.init_temp_db()
        self.init_resolve_db()
        self.check_connectivity()

        # Start the sidecar bot as a daemon thread
        if self.args.debug:
            print(f"Starting sidecar bot with DB at {self.temp_db_path}")
        self.bot_thread, self.bot = run_bot_in_thread(
            self.bot_token, self.temp_db_path
        )
        cur = self.db_conn.cursor()
        while True:
            time.sleep(2)
            messages = cur.execute(
                "select raw_data, created_at from bot_status"
            ).fetchall()
            if messages and json.loads(messages[0][0])["status"] == "ok":
                break

    def close(self):
        """Stop the sidecar bot so its getUpdates poller is released.

        Must be called after the export finishes (success or failure); otherwise
        the daemon polling thread keeps running for the lifetime of the process
        and a later export on the same token raises telegram.error.Conflict.
        """
        if self.bot is not None:
            try:
                self.bot.stop()
            except Exception:
                self.logger.exception("Error stopping sidecar bot")
            self.bot = None
        if self.bot_thread is not None:
            self.bot_thread.join(timeout=30)
            self.bot_thread = None

    def authenticate_user(self):
        print("\n" + "=" * 50)
        print(f"Please send the following code to the bot: {self.auth_uuid}")
        print("This is for security validation.")
        print("=" * 50 + "\n")

        # Wait for authentication
        retry_count = 0
        SLEEP = 2
        max_retries = 300 / SLEEP  # 5 minutes

        while not self.control_chat_id and retry_count < max_retries:
            time.sleep(2)
            cursor = self.db_conn.cursor()
            cursor.execute(
                f"SELECT * FROM messages m WHERE m.raw_data like '%{self.auth_uuid}%' ORDER BY m.created_at DESC LIMIT 1",
            )
            result = cursor.fetchone()

            if result:
                msg_data = json.loads(result["raw_data"])
                if msg_data["message"]["chat"]["type"] != "private":
                    print(
                        "You should post to the PRIVATE chat, not to the channel/group"
                    )
                    continue
                self.control_chat_id = msg_data["message"]["chat"]["id"]
                self.send_api_request(
                    "sendMessage",
                    {
                        "chat_id": self.control_chat_id,
                        "text": "✅ Authentication successful! This chat will be used for control messages.",
                    },
                )

            retry_count += 1

        if not self.control_chat_id:
            self.logger.error("Authentication timeout. Please try again.")
            raise ChgksuiteError("Authentication failed")

    def structure_has_stats(self):
        for element in self.structure:
            if element[0] == "Question" and "Взятия:" in (element[1].get("comment") or ""):
                return True
        return False

    def get_bot_token(self, tg):
        if self.args.tgaccount == "my_account":

            def _getter(x):
                return x["bot_token"]
        else:

            def _getter(x):
                return x["bot_tokens"][self.args.tgaccount]

        try:
            return _getter(tg)
        except KeyError:
            bot_token = input("Please paste your bot token:").strip()

        if self.args.tgaccount == "my_account":

            def _setter(x, y):
                x["bot_token"] = y
        else:

            def _setter(x, y):
                if "bot_tokens" not in y:
                    x["bot_tokens"] = {}
                x["bot_tokens"][self.args.tgaccount] = y

        _setter(tg, bot_token)
        self.save_tg(tg)
        return bot_token

    def get_api_credentials(self):
        """Get or create bot token and channel/discussion IDs from telegram.toml"""
        settings = load_settings()

        if (
            settings.get("stop_if_no_stats")
            and not self.structure_has_stats()
            and not os.environ.get("CHGKSUITE_BYPASS_STATS_CHECK")
        ):
            raise ChgksuiteError("don't publish questions without stats")

        if os.path.exists(self.telegram_toml_path):
            with open(self.telegram_toml_path, "r", encoding="utf8") as f:
                tg = toml.load(f)
        else:
            tg = {}
        return self.get_bot_token(tg)

    def save_tg(self, tg):
        self.logger.info(f"saving {tg}")
        with open(self.telegram_toml_path, "w", encoding="utf8") as f:
            toml.dump(tg, f)

    def send_api_request(self, method, data=None, files=None):
        """Send a request to the Telegram Bot API."""
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        retry_delay = 10  # Start with 10 seconds
        max_retry_delay = 120  # Cap at 2 minutes

        while True:
            try:
                if files:
                    response = self.session.post(
                        url, data=data, files=files, timeout=300
                    )
                else:
                    response = self.session.post(url, json=data, timeout=300)

                response_data = response.json()

                if not response_data.get("ok"):
                    error_message = response_data.get("description", "Unknown error")
                    self.logger.error(f"Telegram API error: {error_message}")

                    # Handle rate limiting
                    if "retry_after" in response_data:
                        retry_after = response_data["retry_after"]
                        self.logger.info(
                            f"Rate limited. Waiting for {retry_after} seconds"
                        )
                        time.sleep(retry_after + 1)
                        return self.send_api_request(method, data, files)

                    raise ChgksuiteError(f"Telegram API error: {error_message}")

                return response_data["result"]
            except requests.exceptions.RequestException as e:
                if isinstance(e, requests.exceptions.ConnectionError) or "Connection reset by peer" in str(e):
                    self.logger.warning(
                        f"Connection error: {e}. Retrying in {retry_delay} seconds..."
                    )
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, max_retry_delay)
                    continue
                self.logger.error(f"Request error: {e}")
                raise

    def get_message_link(self, chat_id, message_id, username=None):
        """Generate a link to a Telegram message."""
        if username:
            # Public channel with username
            return f"https://t.me/{username}/{message_id}"
        else:
            # Private channel, use channel ID
            channel_id_str = str(chat_id)
            # Remove -100 prefix if present
            channel_id_str = channel_id_str.removeprefix("-100")
            return f"https://t.me/c/{channel_id_str}/{message_id}"

    def extract_id_from_link(self, link) -> int | str | None:
        """
        Extract channel or chat ID from a Telegram link.
        Examples:
        - https://t.me/c/1234567890/123 -> 1234567890
        - https://t.me/joinchat/CkzknkZnxkZkZWM0 -> None (not supported)
        - -1001234567890 -> 1234567890
        - @username -> (username, None)  # Returns username for resolution later
        """
        if link is None:
            return None

        if tryint(link) and link.startswith("-100"):
            return int(link[4:])
        elif tryint(link):
            return int(link)

        # Handle username format
        if link.startswith("@"):
            return link[1:]

        # Handle URL format for private channels (with numeric ID)
        link_pattern = r"https?://t\.me/c/(\d+)"
        match = re.search(link_pattern, link)
        if match:
            return int(match.group(1))

        # Handle URL format for public channels (with username)
        public_pattern = r"https?://t\.me/([^/]+)"
        match = re.search(public_pattern, link)
        if match:
            return match.group(1)

        return link

    def tgyapper(self, e):
        if isinstance(e, str):
            return self.tg_element_layout(e)
        elif isinstance(e, list):
            if not any(isinstance(x, list) for x in e):
                return self.tg_element_layout(e)
            else:
                res = []
                images = []
                for x in e:
                    res_, images_ = self.tg_element_layout(x)
                    images.extend(images_)
                    res.append(res_)
                return "\n".join(res), images

    def tg_replace_chars(self, str_):
        if getattr(self, "rich_mode", False):
            str_ = str_.replace("&", "&amp;")
        if not self.args.disable_asterisks_processing:
            str_ = str_.replace("*", "&#42;")
        str_ = str_.replace("_", "&#95;")
        str_ = str_.replace(">", "&gt;")
        str_ = str_.replace("<", "&lt;")
        return str_

    def tgformat(self, s):
        res = ""
        image = None
        tgr = self.tg_replace_chars

        for run in self.parse_4s_elem(s):
            if run[0] == "":
                res += tgr(run[1])
            elif run[0] == "hyperlink":
                res += _format_html_hyperlink(
                    run[1], self.args.disable_asterisks_processing
                )
            elif run[0] == "screen":
                res += tgr(run[1]["for_screen"])
            elif run[0] == "strike":
                res += f"<s>{tgr(run[1])}</s>"
            elif "italic" in run[0] or "bold" in run[0] or "underline" in run[0]:
                chunk = tgr(run[1])
                if "italic" in run[0]:
                    chunk = f"<i>{chunk}</i>"
                if "bold" in run[0]:
                    chunk = f"<b>{chunk}</b>"
                if "underline" in run[0]:
                    chunk = f"<u>{chunk}</u>"
                res += chunk
            elif run[0] == "linebreak":
                res += "\n"
            elif run[0] == "img":
                rich_mode = getattr(self, "rich_mode", False)
                if run[1].startswith(("http://", "https://")):
                    res += run[1]
                else:
                    if not rich_mode:
                        # In rich mode the image is embedded in the message,
                        # no need for a textual placeholder.
                        res += self.labels["general"].get(
                            "cf_image", "см. изображение"
                        )
                    parsed_image = parseimg(
                        run[1],
                        dimensions="ems",
                        targetdir=self.dir_kwargs.get("targetdir"),
                        tmp_dir=self.dir_kwargs.get("tmp_dir"),
                    )
                    imgfile = parsed_image["imgfile"]
                    if os.path.isfile(imgfile):
                        max_side = 800 if self.args.resize_images else None
                        orig_size = Image.open(imgfile).size
                        prepared = self.prepare_image_for_telegram(
                            imgfile, max_side=max_side
                        )
                        if max_side and max(orig_size) > max_side:
                            self.logger.info(
                                f"Resized image {imgfile}: {orig_size[0]}x{orig_size[1]} -> max {max_side}px"
                            )
                        if rich_mode:
                            # Inline sentinel; resolved to an <img> block with
                            # display dimensions when the message is finalized.
                            res += f"\x00img:{prepared}\x00"
                        else:
                            image = prepared
                    else:
                        raise FileNotFoundError(f"image {run[1]} doesn't exist")
            else:
                raise ChgksuiteError(f"unsupported tag `{run[0]}` in telegram export")
        while res.endswith("\n"):
            res = res[:-1]
        return res, image

    @classmethod
    def prepare_image_for_telegram(cls, imgfile, max_side=None, max_height=None):
        """Prepare an image for uploading to Telegram (resize if needed)."""
        img = Image.open(imgfile)
        width, height = img.size
        file_size = os.path.getsize(imgfile)
        modified = False

        if max_side and max(width, height) > max_side:
            scale = max_side / max(width, height)
            img = img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
            width, height = img.size
            modified = True

        if max_height and height > max_height:
            scale = max_height / height
            img = img.resize((int(width * scale), max_height), Image.LANCZOS)
            width, height = img.size
            modified = True

        aspect_ratio = max(width, height) / min(width, height)
        if aspect_ratio >= 20:
            modified = True
            if width > height:
                new_height = width // 19  # Keep ratio slightly under 20
                padding = (0, (new_height - height) // 2)
                img = ImageOps.expand(img, padding, fill="white")
            else:
                new_width = height // 19  # Keep ratio slightly under 20
                padding = ((new_width - width) // 2, 0)
                img = ImageOps.expand(img, padding, fill="white")
            width, height = img.size

        if width + height >= 10000:
            modified = True
            scale_factor = 10000 / (width + height)
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            # Ensure longest side is 1000px max
            if max(new_width, new_height) > 1000:
                if new_width > new_height:
                    scale = 1000 / new_width
                else:
                    scale = 1000 / new_height
                new_width = int(new_width * scale)
                new_height = int(new_height * scale)
            img = img.resize((new_width, new_height), Image.LANCZOS)

        # Check file size (10MB = 10 * 1024 * 1024 bytes)
        if file_size > 10 * 1024 * 1024 or modified:
            base, _ = os.path.splitext(imgfile)
            new_imgfile = f"{base}_telegram.jpg"

            # Convert to JPG and save with reduced quality if necessary
            quality = 95
            while quality >= 70:
                save_pil_image_as_jpeg(img, new_imgfile, quality=quality)
                new_size = os.path.getsize(new_imgfile)
                if new_size <= 10 * 1024 * 1024:
                    break
                quality -= 5

            # If we still can't get it under 10MB, resize more
            if os.path.getsize(new_imgfile) > 10 * 1024 * 1024:
                width, height = img.size
                scale_factor = 0.9  # Reduce by 10% each iteration
                while (
                    os.path.getsize(new_imgfile) > 10 * 1024 * 1024
                    and min(width, height) > 50
                ):
                    width = int(width * scale_factor)
                    height = int(height * scale_factor)
                    resized_img = img.resize((width, height), Image.LANCZOS)
                    save_pil_image_as_jpeg(
                        resized_img, new_imgfile, quality=quality
                    )

            return new_imgfile

        return imgfile

    def tg_element_layout(self, e):
        res = ""
        images = []
        if isinstance(e, str):
            res, image = self.tgformat(e)
            if image:
                images.append(image)
            return res, images
        if isinstance(e, list):
            result = []
            for i, x in enumerate(e):
                res_, images_ = self.tg_element_layout(x)
                images.extend(images_)
                result.append(f"{i + 1}. {res_}")
            res = "\n".join(result)
        return res, images

    def _post_rich(self, chat_id, payload, reply_to_message_id=None):
        """Send a rich message (Bot API 10.1 sendRichMessage).

        ``payload`` is a dict with ``html`` and ``media_files``
        (list of (media_id, path) referenced as tg://photo?id=<media_id>).
        """
        html_content = payload["html"]
        self.logger.info(f"Posting rich message: {html_content[:50]}...")
        media = []
        files = {}
        with contextlib.ExitStack() as stack:
            for media_id, path in payload.get("media_files", []):
                attach_name = f"f{media_id}"
                files[attach_name] = stack.enter_context(open(path, "rb"))
                media.append(
                    {
                        "id": media_id,
                        "media": {"type": "photo", "media": f"attach://{attach_name}"},
                    }
                )
            rich_message = {"html": html_content}
            if media:
                rich_message["media"] = media
            if files:
                # Multipart request: non-file fields must be serialized strings.
                data = {
                    "chat_id": chat_id,
                    "rich_message": json.dumps(rich_message),
                    "disable_notification": "true",
                }
                if reply_to_message_id:
                    data["reply_parameters"] = json.dumps(
                        {"message_id": reply_to_message_id}
                    )
                result = self.send_api_request("sendRichMessage", data, files)
            else:
                data = {
                    "chat_id": chat_id,
                    "rich_message": rich_message,
                    "disable_notification": True,
                }
                if reply_to_message_id:
                    data["reply_parameters"] = {"message_id": reply_to_message_id}
                result = self.send_api_request("sendRichMessage", data)
        return {"message_id": result["message_id"], "chat": {"id": chat_id}}

    def _post(self, chat_id, text, photo, reply_to_message_id=None):
        """Send a message to Telegram using API requests."""
        if isinstance(text, dict):
            return self._post_rich(
                chat_id, text, reply_to_message_id=reply_to_message_id
            )
        self.logger.info(f"Posting message: {text[:50]}...")

        try:
            if photo:
                # Step 1: Upload the photo first
                with open(photo, "rb") as photo_file:
                    files = {"photo": photo_file}
                    caption = "" if not text else ("---" if text != "---" else "--")

                    data = {
                        "chat_id": chat_id,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "disable_notification": True,
                    }

                    if reply_to_message_id:
                        data["reply_to_message_id"] = reply_to_message_id

                    result = self.send_api_request("sendPhoto", data, files)
                    msg_id = result["message_id"]

                # Step 2: Edit the message if needed to add full text
                if text and text != "---":
                    time.sleep(2)  # Slight delay before editing
                    edit_data = {
                        "chat_id": chat_id,
                        "message_id": msg_id,
                        "caption": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    }
                    result = self.send_api_request("editMessageCaption", edit_data)

                return {"message_id": msg_id, "chat": {"id": chat_id}}
            else:
                # Simple text message
                data = {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "disable_notification": True,
                }

                if reply_to_message_id:
                    data["reply_to_message_id"] = reply_to_message_id

                result = self.send_api_request("sendMessage", data)
                return {"message_id": result["message_id"], "chat": {"id": chat_id}}

        except Exception as e:
            self.logger.error(f"Error posting message: {e!s}")
            raise

    def post(self, posts):
        """Post a series of messages, handling the channel and discussion group."""
        if self.args.dry_run:
            self.logger.info("Skipping posting due to dry run")
            for post in posts:
                self.logger.info(post)
            self._dry_run_msg_counter = getattr(self, "_dry_run_msg_counter", 0) + 1
            return [{"message_id": self._dry_run_msg_counter, "chat": {"id": 0}}]

        messages = []
        text, im = posts[0]
        is_qqq = isinstance(text, str) and text.startswith("QQQ")

        # Step 1: Post the root message to the channel
        root_msg = self._post(
            self.channel_id,
            self.labels["general"]["handout_for_question"].format(text[3:])
            if is_qqq
            else text,
            im,
        )

        # Handle special case for questions with images
        if len(posts) >= 2 and is_qqq and im and posts[1][0]:
            prev_root_msg = root_msg
            root_msg = self._post(self.channel_id, posts[1][0], posts[1][1])
            posts = posts[1:]
            messages.append(root_msg)
            messages.append(prev_root_msg)

        time.sleep(2.1)

        # Step 2: Wait for the message to appear in the discussion group
        root_msg_in_discussion_id = self.get_discussion_message(
            self.channel_id, root_msg["message_id"]
        )

        if not root_msg_in_discussion_id:
            self.logger.error("Failed to find discussion message")
            return

        self._last_discussion_msg_id = root_msg_in_discussion_id

        root_msg_in_discussion = {
            "message_id": root_msg_in_discussion_id,
            "chat": {"id": self.chat_id},
        }

        # Create message links
        root_msg_link = self.get_message_link(self.channel_id, root_msg["message_id"])
        root_msg_in_discussion_link = self.get_message_link(
            self.chat_id, root_msg_in_discussion_id
        )

        self.logger.info(
            f"Posted message {root_msg_link} ({root_msg_in_discussion_link} in discussion group)"
        )

        time.sleep(random.randint(5, 7))

        if root_msg not in messages:
            messages.append(root_msg)
        messages.append(root_msg_in_discussion)

        # Step 3: Post replies in the discussion group
        for post in posts[1:]:
            text, im = post
            reply_msg = self._post(
                self.chat_id,
                text,
                im,
                reply_to_message_id=root_msg_in_discussion_id,
            )
            self.logger.info(
                f"Replied to message {root_msg_in_discussion_link} with reply message"
            )
            time.sleep(random.randint(5, 7))
            messages.append(reply_msg)

        return messages

    def post_wrapper(self, posts):
        """Wrapper for post() that handles section links and tour tracking."""
        messages = self.post(posts)
        if messages:
            link = self.get_message_link(self.channel_id, messages[0]["message_id"])
            if self.si_mode and self._si_pending_group is not None:
                self._si_nav.append(
                    {"type": "group", "name": self._si_pending_group, "link": link}
                )
                self._si_pending_group = None
            if self.section:
                if self.si_mode:
                    self._si_nav.append(
                        {
                            "type": "theme",
                            "num": self._si_current_theme_number,
                            "name": self._si_current_theme_name,
                            "link": link,
                        }
                    )
                else:
                    self.section_links.append((link, self._tour_number))
                self._tour_discussion_msg_id = self._last_discussion_msg_id
        self.section = False

    def _extract_tour_number(self, section_text):
        """Extract tour number from section text, e.g. 'Тур 3' -> '3'."""
        m = re.search(r"(\d+)", section_text)
        if m:
            return m.group(1)
        return section_text

    def tg_process_element(self, pair):
        if pair[0] == "Question":
            q = pair[1]
            if "setcounter" in q:
                self.qcount = int(q["setcounter"])
            number = q.get("number", self.qcount)
            if not self.si_mode:
                self.qcount += 1
            self.number = number
            if self.args.skip_until and (
                not tryint(number) or tryint(number) < self.args.skip_until
            ):
                self.logger.info(f"skipping question {number}")
                return
            if self.si_mode:
                text, images = self.tg_format_question(pair[1], number=number)
                self.buffer_texts.append(text)
                self.buffer_images.extend(images)
            else:
                if self.buffer_texts or self.buffer_images:
                    posts = self.split_to_messages(self.buffer_texts, self.buffer_images)
                    self.post_wrapper(posts)
                    self.buffer_texts = []
                    self.buffer_images = []
                posts = self.tg_format_question(pair[1], number=number)
                self.post_wrapper(posts)
                if self._polls_enabled:
                    self._post_question_poll(number)
        elif self.args.skip_until and (
            not tryint(self.number) or tryint(self.number) < self.args.skip_until
        ):
            self.logger.info(f"skipping element {pair[0]}")
            return
        elif pair[0] == "heading":
            text, images = self.tg_element_layout(pair[1])
            if not self.tg_heading:
                self.tg_heading = text
            self.buffer_texts.append(self._wrap_heading(text))
            self.buffer_images.extend(images)
        elif pair[0] == "section":
            if self.buffer_texts or self.buffer_images:
                posts = self.split_to_messages(self.buffer_texts, self.buffer_images)
                self.post_wrapper(posts)
                self.buffer_texts = []
                self.buffer_images = []
            # Post tour poll for the previous tour before starting a new one
            if self._polls_enabled:
                self._post_tour_poll()
            text, images = self.tg_element_layout(pair[1])
            self._tour_number = self._extract_tour_number(text)
            self._tour_seq += 1
            self.buffer_texts.append(self._wrap_heading(text))
            self.buffer_images.extend(images)
            if self.si_mode:
                self._si_pending_group = text
            else:
                self.section = True
        elif pair[0] == "battle":
            if self.buffer_texts or self.buffer_images:
                posts = self.split_to_messages(self.buffer_texts, self.buffer_images)
                self.post_wrapper(posts)
                self.buffer_texts = []
                self.buffer_images = []
            text, images = self.tg_element_layout(pair[1])
            self.buffer_texts.append(self._wrap_heading(text))
            self.buffer_images.extend(images)
            self._si_pending_group = text
        elif pair[0] == "theme":
            if self.buffer_texts or self.buffer_images:
                posts = self.split_to_messages(self.buffer_texts, self.buffer_images)
                self.post_wrapper(posts)
                self.buffer_texts = []
                self.buffer_images = []
            if self._polls_enabled:
                self._post_tour_poll()
            self._si_current_theme_name = pair[1]["name"]
            self._si_current_theme_number = pair[1]["number"]
            theme_label = pair[1]["label"]
            text, images = self.tg_element_layout(theme_label)
            self._tour_number = str(pair[1]["number"])
            self._tour_seq += 1
            self.buffer_texts.append(self._wrap_heading(text))
            self.buffer_images.extend(images)
            self.section = True
        elif pair[0] == "round":
            if self.buffer_texts or self.buffer_images:
                posts = self.split_to_messages(self.buffer_texts, self.buffer_images)
                self.post_wrapper(posts)
                self.buffer_texts = []
                self.buffer_images = []
            text, images = self.tg_element_layout(pair[1])
            self.buffer_texts.append(self._wrap_heading(text))
            self.buffer_images.extend(images)
            self._si_pending_group = text
        elif pair[0] in ("comment", "author") and self.si_mode:
            field_label = self.labels["question_labels"].get(
                pair[0], pair[0].capitalize()
            )
            text, images = self.tg_element_layout(pair[1])
            if text:
                formatted = f"<b>{field_label}:</b> {text}"
                if self.buffer_texts and not self.rich_mode:
                    self.buffer_texts[-1] += "\n" + formatted
                else:
                    self.buffer_texts.append(formatted)
            if images:
                self.buffer_images.extend(images)
        else:
            text, images = self.tg_element_layout(pair[1])
            if text:
                if self.si_mode and self.buffer_texts and not self.rich_mode:
                    self.buffer_texts[-1] += "\n" + text
                else:
                    self.buffer_texts.append(text)
            if images:
                self.buffer_images.extend(images)

    def assemble(self, list_, lb_after_first=False):
        list_ = [x for x in list_ if x]
        list_ = [
            x.strip()
            for x in list_
            if not x.startswith(("\n</tg-spoiler>", "\n<tg-spoiler>"))
        ]
        if lb_after_first:
            list_[0] = list_[0] + "\n"
        res = "\n".join(list_)
        res = res.replace("\n</tg-spoiler>\n", "\n</tg-spoiler>")
        res = res.replace("\n<tg-spoiler>\n", "\n<tg-spoiler>")
        while res.endswith("\n"):
            res = res[:-1]
        if res.endswith("\n</tg-spoiler>"):
            res = res[:-len("\n</tg-spoiler>")] + "</tg-spoiler>"
        if self.args.nospoilers:
            res = res.replace("<tg-spoiler>", "")
            res = res.replace("</tg-spoiler>", "")
        res = res.replace("`", "'")  # hack so spoilers don't break
        return res

    def make_chunk(self, texts, images):
        if isinstance(texts, str):
            texts = [texts]
        if images:
            im, images = images[0], images[1:]
            threshold = 1024
        else:
            im = None
            threshold = 4096
        if not texts:
            return "", im, texts, images
        if tg_len(texts[0]) <= threshold:
            for i in range(len(texts)):
                if i:
                    candidate = texts[:-i]
                else:
                    candidate = texts
                if self.si_mode:
                    text = "\n\n".join(t for t in candidate if t)
                else:
                    text = self.assemble(candidate)
                if tg_len(text) <= threshold:
                    if i:
                        texts = texts[-i:]
                    else:
                        texts = []
                    return text, im, texts, images
        else:
            threshold_ = threshold - 3
            chunk = texts[0][:threshold_]
            rest = texts[0][threshold_:]
            if texts[0].endswith("</tg-spoiler>"):
                chunk += "</tg-spoiler>"
                rest = "<tg-spoiler>" + rest
            texts[0] = rest
            return chunk, im, texts, images

    def split_to_messages(self, texts, images):
        if self.rich_mode:
            return self._split_to_messages_rich(texts, images)
        result = []
        while texts or images:
            chunk, im, texts, images = self.make_chunk(texts, images)
            if chunk or im:
                result.append((chunk, im))
        return result

    def _wrap_heading(self, text):
        return f"<h3>{text}</h3>" if self.rich_mode else f"<b>{text}</b>"

    @staticmethod
    def _rich_br(text):
        return text.replace("\n", "<br/>")

    def _rich_render(self, text):
        """Convert plain text with image sentinels into rich HTML blocks."""
        parts = []
        pos = 0
        for m in _TG_IMG_SENTINEL_RE.finditer(text):
            seg = text[pos : m.start()].strip()
            if seg:
                parts.append(f"<p>{self._rich_br(seg)}</p>")
            parts.append(m.group(0))
            pos = m.end()
        seg = text[pos:].strip()
        if seg:
            parts.append(f"<p>{self._rich_br(seg)}</p>")
        return "".join(parts)

    # Rich messages render photos at intrinsic size and ignore width/height
    # attributes, so physically resize to keep images modest.
    RICH_IMG_DISPLAY_HEIGHT = 200

    def _finalize_rich(self, html_content):
        """Replace image sentinels with <img> blocks, collect media files."""
        media_files = []

        def repl(m):
            path = self.prepare_image_for_telegram(
                m.group(1), max_height=self.RICH_IMG_DISPLAY_HEIGHT
            )
            media_id = f"img{len(media_files)}"
            media_files.append((media_id, path))
            return f'<img src="tg://photo?id={media_id}"/>'

        return _TG_IMG_SENTINEL_RE.sub(repl, html_content), media_files

    def _split_to_messages_rich(self, texts, images):
        html_parts = []
        for t in texts:
            t = (t or "").strip()
            if not t:
                continue
            # Already-rendered fragments (headings, si questions) contain
            # block tags; plain text never does (< and > are escaped).
            if t.startswith("<h") or "</p>" in t or "<details>" in t:
                html_parts.append(t)
            else:
                html_parts.append(self._rich_render(t))
        # Images normally arrive as inline sentinels; keep stragglers anyway.
        html_parts.extend(f"\x00img:{path}\x00" for path in images)
        if not html_parts:
            return []
        html_content, media_files = self._finalize_rich("".join(html_parts))
        if len(html_content) > 32000:
            self.logger.warning(
                f"rich message length {len(html_content)} may exceed "
                "the 32768-character Telegram limit"
            )
        return [({"html": html_content, "media_files": media_files}, None)]

    def swrap(self, s_, t="both"):
        if not s_:
            res = s_
        if self.args.nospoilers:
            res = s_
        elif t == "both":
            res = "<tg-spoiler>" + s_ + "</tg-spoiler>"
        elif t == "left":
            res = "<tg-spoiler>" + s_
        elif t == "right":
            res = s_ + "</tg-spoiler>"
        return res

    @staticmethod
    def lwrap(l_, lb_after_first=False):
        l_ = [x.strip() for x in l_ if x]
        if lb_after_first:
            return l_[0] + "\n" + "\n".join([x for x in l_[1:]])
        return "\n".join(l_)

    def _format_question_parts(self, q, number=None):
        """Render each labeled field of a question into HTML-tagged text blocks.

        Returns a dict with keys ``q`` / ``a`` / ``z`` / ``nz`` / ``comm`` / ``s`` / ``au``
        plus ``images_q`` (question-side images) and ``images_a`` (answer-side images).
        """
        txt_q, images_q = self.tgyapper(q["question"])
        if self.si_mode:
            q_label = str(number)
        else:
            q_label = self.get_label(q, "question", number=number)
            if "number" not in q:
                self.qcount += 1
        # SI's theme-level post concatenates questions with "\n\n" separators,
        # so the extra trailing whitespace ChGK adds isn't needed there.
        txt_q = (
            f"<b>{q_label}:</b> {txt_q}"
            if self.si_mode
            else f"<b>{q_label}:</b> {txt_q}  \n"
        )
        images_a = []
        txt_a, images_ = self.tgyapper(q["answer"])
        images_a.extend(images_)
        txt_a = "<b>{}:</b> {}".format(self.get_label(q, "answer"), txt_a)
        txt_z = ""
        txt_nz = ""
        txt_comm = ""
        txt_s = ""
        txt_au = ""
        if "zachet" in q:
            txt_z, images_ = self.tgyapper(q["zachet"])
            images_a.extend(images_)
            txt_z = "<b>{}:</b> {}".format(self.get_label(q, "zachet"), txt_z)
        if "nezachet" in q:
            txt_nz, images_ = self.tgyapper(q["nezachet"])
            images_a.extend(images_)
            txt_nz = "<b>{}:</b> {}".format(self.get_label(q, "nezachet"), txt_nz)
        if "comment" in q:
            txt_comm, images_ = self.tgyapper(q["comment"])
            images_a.extend(images_)
            txt_comm = "<b>{}:</b> {}".format(self.get_label(q, "comment"), txt_comm)
        if "source" in q:
            txt_s, images_ = self.tgyapper(q["source"])
            images_a.extend(images_)
            txt_s = f"<b>{self.get_label(q, 'source')}:</b> {txt_s}"
        if "author" in q:
            txt_au, images_ = self.tgyapper(q["author"])
            images_a.extend(images_)
            txt_au = f"<b>{self.get_label(q, 'author')}:</b> {txt_au}"
        return {
            "q": txt_q,
            "a": txt_a,
            "z": txt_z,
            "nz": txt_nz,
            "comm": txt_comm,
            "s": txt_s,
            "au": txt_au,
            "images_q": images_q,
            "images_a": images_a,
        }

    def tg_format_question_rich(self, q, number=None):
        """Render a question as a single rich HTML fragment.

        Question text and handout images stay visible; answer, comment etc.
        are collapsed in a <details> block, source/author go to a <footer>
        (rendered smaller). Images stay as inline sentinels; for si the raw
        fragment is returned for buffering, otherwise it is finalized into
        a single-message payload.
        """
        parts = self._format_question_parts(q, number=number)
        # Unwrap "[Раздаточный материал: <img>]" — the image needs no wrapper
        # now that it is embedded in the message.
        handout_label = self.labels["question_labels"]["handout"]
        txt_q = re.sub(
            r"\[" + re.escape(handout_label) + r":\s*(\x00img:[^\x00]+\x00)\s*\]",
            r"\1",
            parts["q"],
        )
        html_content = self._rich_render(txt_q.strip())
        hidden = "\n".join(parts[k] for k in ("a", "z", "nz", "comm") if parts[k])
        body = self._rich_render(hidden)
        small = "\n".join(parts[k] for k in ("s", "au") if parts[k])
        if small:
            # <footer> holds only text; image blocks move after it
            footer_imgs = _TG_IMG_SENTINEL_RE.findall(small)
            small = _TG_IMG_SENTINEL_RE.sub("", small)
            body += f"<footer>{self._rich_br(small.strip())}</footer>"
            body += "".join(f"\x00img:{path}\x00" for path in footer_imgs)
        if body:
            if self.args.nospoilers:
                html_content += body
            else:
                summary = self.labels["question_labels"]["answer"]
                html_content += (
                    f"<details><summary>{summary}</summary>{body}</details>"
                )
        if self.si_mode:
            # Buffered per theme; finalized later in _split_to_messages_rich.
            return html_content, []
        html_content, media_files = self._finalize_rich(html_content)
        if len(html_content) > 32000:
            self.logger.warning(
                f"question {number}: rich message length {len(html_content)} "
                "may exceed the 32768-character Telegram limit"
            )
        return [({"html": html_content, "media_files": media_files}, None)]

    def tg_format_question(self, q, number=None):
        if self.rich_mode:
            return self.tg_format_question_rich(q, number=number)
        parts = self._format_question_parts(q, number=number)
        txt_q = parts["q"]
        txt_a = parts["a"]
        txt_z = parts["z"]
        txt_nz = parts["nz"]
        txt_comm = parts["comm"]
        txt_s = parts["s"]
        txt_au = parts["au"]
        images_q = parts["images_q"]
        images_a = parts["images_a"]
        if self.si_mode:
            # SI buffers a single chunk per question — caller handles splitting.
            text = self.assemble(
                [
                    txt_q,
                    self.swrap(txt_a, t="left"),
                    txt_z,
                    txt_nz,
                    txt_comm,
                    self.swrap(txt_s, t="right"),
                    txt_au,
                ],
                lb_after_first=True,
            )
            return text, list(images_q) + images_a
        q_threshold = 4096 if not images_q else 1024
        full_question = self.assemble(
            [
                txt_q,
                self.swrap(txt_a, t="left"),
                txt_z,
                txt_nz,
                txt_comm,
                self.swrap(txt_s, t="right"),
                txt_au,
            ],
            lb_after_first=True,
        )
        if tg_len(full_question) <= q_threshold:
            res = [(full_question, images_q[0] if images_q else None)]
            for i in images_a:
                res.append(("", i))
            return res
        elif images_q and tg_len(full_question) <= 4096:
            full_question = re.sub(
                "\\[" + self.labels["question_labels"]["handout"] + ": +?\\]\n",
                "",
                full_question,
            )
            res = [(f"QQQ{number}", images_q[0]), (full_question, None)]
            for i in images_a:
                res.append(("", i))
            return res
        q_without_s = self.assemble(
            [
                txt_q,
                self.swrap(txt_a, t="left"),
                txt_z,
                txt_nz,
                self.swrap(txt_comm, t="right"),
            ],
            lb_after_first=True,
        )
        if tg_len(q_without_s) <= q_threshold:
            res = [(q_without_s, images_q[0] if images_q else None)]
            res.extend(
                self.split_to_messages(
                    self.lwrap([self.swrap(txt_s), txt_au]), images_a
                )
            )
            return res
        q_a_only = self.assemble([txt_q, self.swrap(txt_a)], lb_after_first=True)
        if tg_len(q_a_only) <= q_threshold:
            res = [(q_a_only, images_q[0] if images_q else None)]
            res.extend(
                self.split_to_messages(
                    self.lwrap(
                        [
                            self.swrap(txt_z),
                            self.swrap(txt_nz),
                            self.swrap(txt_comm),
                            self.swrap(txt_s),
                            txt_au,
                        ]
                    ),
                    images_a,
                )
            )
            return res
        return self.split_to_messages(
            self.lwrap(
                [
                    txt_q,
                    self.swrap(txt_a),
                    self.swrap(txt_z),
                    self.swrap(txt_nz),
                    self.swrap(txt_comm),
                    self.swrap(txt_s),
                    txt_au,
                ],
                lb_after_first=True,
            ),
            (images_q or []) + (images_a or []),
        )

    @staticmethod
    def is_valid_tg_identifier(str_):
        str_ = str_.strip()
        if not str_.startswith("-"):
            return
        return tryint(str_)

    def _load_poll_config(self):
        """Load poll configuration from TOML file."""
        with open(self.args.poll_config, "r", encoding="utf-8") as f:
            cfg = toml.load(f)
        self.poll_mode = cfg.get("mode", "comment")
        self.poll_config = {}
        for key in ("question_poll", "tour_poll", "packet_poll"):
            if key in cfg:
                self.poll_config[key] = cfg[key]

    def _post_poll(self, chat_id, poll_cfg, substitutions, reply_to_message_id=None):
        """Post a poll to Telegram.

        Args:
            chat_id: Chat to post to.
            poll_cfg: Dict with 'text', 'variants', and optional 'quiz_right_answer'.
            substitutions: Dict for {NUMBER}, {TITLE} replacement.
            reply_to_message_id: Optional message ID to reply to.
        """
        question_text = poll_cfg["text"]
        for k, v in substitutions.items():
            question_text = question_text.replace(f"{{{k}}}", str(v))

        options = poll_cfg["variants"]

        data = {
            "chat_id": chat_id,
            "question": question_text,
            "options": json.dumps(options),
            "is_anonymous": poll_cfg.get("is_anonymous", True),
            "disable_notification": True,
        }

        if "quiz_right_answer" in poll_cfg:
            data["type"] = "quiz"
            try:
                data["correct_option_id"] = options.index(poll_cfg["quiz_right_answer"])
            except ValueError:
                self.logger.warning(
                    f"quiz_right_answer '{poll_cfg['quiz_right_answer']}' not in variants, falling back to regular poll"
                )
                data["type"] = "regular"
        else:
            data["type"] = "regular"
            if "allows_revoting" in poll_cfg:
                data["allows_revoting"] = poll_cfg["allows_revoting"]

        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id

        if self.args.dry_run:
            self.logger.info(f"[dry_run] Would post poll: {question_text}")
            return None

        try:
            result = self.send_api_request("sendPoll", data)
            self.logger.info(f"Posted poll: {question_text}")
            time.sleep(random.randint(2, 4))
            return result
        except Exception:
            self.logger.exception("Failed to post poll")
            return None

    def _disable_reactions(self, channel_id):
        """Disable emoji reactions on the channel when polls are active."""
        if self.args.dry_run:
            self.logger.info("[dry_run] Would disable reactions on channel")
            return
        try:
            self.send_api_request(
                "setChatAvailableReactions",
                {"chat_id": channel_id, "available_reactions": json.dumps([])},
            )
            self.logger.info("Disabled emoji reactions on channel")
        except Exception:
            self.logger.exception(
                "Could not disable reactions (bot may lack permissions)"
            )

    def _post_question_poll(self, number):
        """Post a question poll if configured."""
        if not self.poll_config.get("question_poll"):
            return
        cfg = self.poll_config["question_poll"]
        if self.poll_mode == "comment" and self._last_discussion_msg_id:
            self._post_poll(
                self.chat_id,
                cfg,
                {"NUMBER": number},
                reply_to_message_id=self._last_discussion_msg_id,
            )
        else:
            self._post_poll(self.channel_id, cfg, {"NUMBER": number})

    def _post_tour_poll(self):
        """Post a tour poll for the current tour if configured."""
        if not self.poll_config.get("tour_poll"):
            return
        if self._tour_number is None:
            return
        cfg = self.poll_config["tour_poll"]
        if self.poll_mode == "comment" and self._tour_discussion_msg_id:
            self._post_poll(
                self.chat_id,
                cfg,
                {"NUMBER": self._tour_number},
                reply_to_message_id=self._tour_discussion_msg_id,
            )
        else:
            self._post_poll(self.channel_id, cfg, {"NUMBER": self._tour_number})

    def _post_packet_poll(self, nav_discussion_msg_id=None):
        """Post a packet poll if configured."""
        if not self.poll_config.get("packet_poll"):
            return
        cfg = self.poll_config["packet_poll"]
        title = self.tg_heading or ""
        if self.poll_mode == "comment" and nav_discussion_msg_id:
            self._post_poll(
                self.chat_id,
                cfg,
                {"TITLE": title},
                reply_to_message_id=nav_discussion_msg_id,
            )
        else:
            self._post_poll(self.channel_id, cfg, {"TITLE": title})

    def export(self):
        """Main export function to send the structure to Telegram."""
        self.section_links = []
        self.buffer_texts = []
        self.buffer_images = []
        self.section = False
        self._last_discussion_msg_id = None
        self._tour_discussion_msg_id = None
        self._tour_number = None
        self._tour_seq = 0
        self._si_nav = []
        self._si_pending_group = None
        self._si_current_theme_name = None
        self._si_current_theme_number = None
        self._polls_enabled = getattr(self.args, "add_polls", False)
        self.poll_config = {}
        self.poll_mode = "comment"

        if not self.args.tgchannel or not self.args.tgchat:
            raise ChgksuiteError("Please provide channel and chat links or IDs.")

        # Try to extract IDs from links or direct ID inputs
        channel_result = self.extract_id_from_link(self.args.tgchannel)
        chat_result = self.extract_id_from_link(self.args.tgchat)

        # First, try to resolve both IDs without user interaction
        channel_id = None
        chat_id = None
        needs_channel_interaction = False
        needs_chat_interaction = False

        if isinstance(channel_result, int):
            channel_id = channel_result
        elif isinstance(channel_result, str):
            channel_id = self.resolve_username_to_id(channel_result)
            if not channel_id:
                needs_channel_interaction = True
        else:
            raise TypeError("Channel ID is undefined")

        if isinstance(chat_result, int):
            chat_id = chat_result
        elif isinstance(chat_result, str):
            chat_id = self.resolve_username_to_id(chat_result)
            if not chat_id:
                needs_chat_interaction = True
        else:
            raise TypeError("Chat ID is undefined")

        # Only authenticate if we need user interaction
        if needs_channel_interaction or needs_chat_interaction:
            self.authenticate_user()

        # Handle channel resolution with user interaction if needed
        if needs_channel_interaction:
            print("\n" + "=" * 50)
            print("Please forward any message from the target channel to the bot.")
            print("This will allow me to extract the channel ID automatically.")
            print("=" * 50 + "\n")

            # Wait for a forwarded message with channel information
            channel_id = self.wait_for_forwarded_message(
                entity_type="channel", check_type=True
            )
            if channel_id:
                self.save_username(channel_result, channel_id)
            else:
                raise ChgksuiteError("Failed to get channel ID from forwarded message")

        # Handle chat resolution with user interaction if needed
        if needs_chat_interaction:
            print("\n" + "=" * 50)
            print(
                f"Please write a message in the discussion group with text: {self.chat_auth_uuid}"
            )
            print("This will allow me to extract the group ID automatically.")
            print(
                "The bot MUST be added do the group and made admin, else it won't work!"
            )
            print("=" * 50 + "\n")

            # Wait for a forwarded message with chat information
            chat_id = self.wait_for_forwarded_message(
                entity_type="chat", check_type=False
            )
            if not chat_id:
                self.logger.error("Failed to get chat ID from forwarded message")
                return False
            while chat_id == channel_id:
                error_msg = (
                    "Chat ID and channel ID are the same. The problem may be that "
                    "you posted a message in the channel, not in the discussion group."
                )
                self.logger.error(error_msg)
                chat_id = self.wait_for_forwarded_message(
                    entity_type="chat",
                    check_type=False,
                    add_msg=error_msg,
                )
            if chat_id:
                self.save_username(chat_result, chat_id)

        if not channel_id:
            raise ChgksuiteError("Channel ID is undefined")
        if not chat_id:
            raise ChgksuiteError("Chat ID is undefined")

        self.channel_id = f"-100{channel_id}"
        if not str(chat_id).startswith("-100"):
            self.chat_id = f"-100{chat_id}"
        else:
            self.chat_id = chat_id

        self.logger.info(
            f"Using channel ID {self.channel_id} and discussion group ID {self.chat_id}"
        )

        channel_access = self.verify_access(self.channel_id, hr_type="channel")
        chat_access = self.verify_access(self.chat_id, hr_type="chat")
        if not (channel_access and chat_access):
            bad = []
            if not channel_access:
                bad.append("channel")
            if not chat_access:
                bad.append("discussion group")
            raise ChgksuiteError(f"The bot doesn't have access to {' and '.join(bad)}")

        # Load poll config if polls are enabled
        if self._polls_enabled:
            self._load_poll_config()
            self._disable_reactions(self.channel_id)

        # Process all elements
        for pair in self.structure:
            self.tg_process_element(pair)

        # Handle any remaining buffer
        if self.buffer_texts or self.buffer_images:
            posts = self.split_to_messages(self.buffer_texts, self.buffer_images)
            self.post_wrapper(posts)
            self.buffer_texts = []
            self.buffer_images = []

        # Post tour poll for the last tour (not triggered by a next section)
        if self._polls_enabled:
            self._post_tour_poll()

        # Create and pin navigation message with links to sections
        if not self.args.skip_until:
            navigation_lines = [self.labels["general"]["general_impressions_text"]]
            if self.tg_heading:
                navigation_lines = [
                    f"<b>{self.tg_heading}</b>",
                    "",
                ] + navigation_lines

            if self.si_mode:
                # SI navigation: main post has stages/battles only,
                # comments have full detail with themes
                header_block = "\n".join(navigation_lines)

                # Build main nav (groups only) and detail nav (groups + themes)
                main_lines = [header_block]
                detail_blocks = [header_block]
                current_themes = []
                current_group_line = None
                for entry in self._si_nav:
                    if entry["type"] == "group":
                        if current_group_line is not None:
                            block = current_group_line
                            if current_themes:
                                block += "\n" + ", ".join(current_themes)
                            detail_blocks.append(block)
                            current_themes = []
                        current_group_line = (
                            f'<b><a href="{entry["link"]}">{entry["name"]}</a></b>'
                        )
                        main_lines.append(current_group_line)
                    elif entry["type"] == "theme":
                        current_themes.append(
                            '<a href="{}">{}.{}{}</a>'.format(
                                entry["link"],
                                entry["num"],
                                "\u00a0" if len(str(entry["num"])) < 2 else " ",
                                entry["name"],
                            )
                        )
                if current_group_line is not None:
                    block = current_group_line
                    if current_themes:
                        block += "\n" + ", ".join(current_themes)
                    detail_blocks.append(block)

                # Main post: just stages/battles
                main_nav_text = "\n".join(main_lines)
                navigation_posts = [(main_nav_text, None)]

                # Detail posts for comments: full blocks with themes
                # Split on both text length (4096) and entity count (100).
                detail_posts = []
                current_msg = ""
                for block in detail_blocks:
                    candidate = (
                        block if not current_msg
                        else current_msg + "\n\n" + block
                    )
                    if (tg_len(candidate) <= 4096
                            and tg_entity_count(candidate) < _TG_MAX_ENTITIES):
                        current_msg = candidate
                    else:
                        if current_msg:
                            detail_posts.append((current_msg, None))
                        current_msg = block
                if current_msg:
                    detail_posts.append((current_msg, None))
            else:
                nav_label = self.labels["general"]["section"]
                for link, tour_number in self.section_links:
                    display = tour_number if tour_number else ""
                    navigation_lines.append(f"{nav_label} {display}: {link}")
                navigation_text = "\n".join(navigation_lines)
                navigation_posts = [(navigation_text, None)]

            # Post the navigation message
            if not self.args.dry_run:
                message = self._post(
                    self.channel_id, navigation_posts[0][0].strip(), None
                )

                # Post detail navigation with themes in discussion thread
                comment_posts = (
                    detail_posts if self.si_mode and detail_posts
                    else navigation_posts[1:]
                )
                if comment_posts:
                    time.sleep(2.1)
                    nav_discussion_msg_id = self.get_discussion_message(
                        self.channel_id, message["message_id"]
                    )
                    for post in comment_posts:
                        self._post(
                            self.chat_id,
                            post[0],
                            post[1],
                            reply_to_message_id=nav_discussion_msg_id,
                        )
                        time.sleep(random.randint(2, 4))

                # Post packet poll under navigation message's discussion thread
                if self._polls_enabled:
                    time.sleep(2.1)
                    nav_discussion_msg_id = self.get_discussion_message(
                        self.channel_id, message["message_id"]
                    )
                    self._post_packet_poll(nav_discussion_msg_id)

                # Pin the message
                try:
                    self.send_api_request(
                        "pinChatMessage",
                        {
                            "chat_id": self.channel_id,
                            "message_id": message["message_id"],
                            "disable_notification": True,
                        },
                    )
                except Exception:
                    self.logger.exception("Failed to pin message")
        return True

    def init_resolve_db(self):
        if not os.path.exists(self.resolve_db_path):
            self.resolve_db_conn = sqlite3.connect(self.resolve_db_path)
            self.resolve_db_conn.execute(
                "CREATE TABLE IF NOT EXISTS resolve (username TEXT PRIMARY KEY, id INTEGER)"
            )
            self.resolve_db_conn.commit()
        else:
            self.resolve_db_conn = sqlite3.connect(self.resolve_db_path)

    def resolve_username_to_id(self, username):
        assert username is not None
        cur = self.resolve_db_conn.cursor()
        cur.execute("SELECT id FROM resolve WHERE username = ?", (username,))
        res = cur.fetchone()
        if res:
            return res[0]
        return None

    def save_username(self, username, id_):
        assert username is not None
        assert id_ is not None
        self.logger.info(f"Saving username {username} as ID {id_}")
        cur = self.resolve_db_conn.cursor()
        cur.execute("INSERT INTO resolve (username, id) VALUES (?, ?)", (username, id_))
        self.resolve_db_conn.commit()

    def get_discussion_message(self, channel_id, message_id):
        """
        Find the corresponding message in the discussion group for a channel message.
        Returns the message_id in the discussion group.
        """
        # Format the channel ID correctly for comparison
        if not str(channel_id).startswith("-100"):
            formatted_channel_id = f"-100{channel_id}"
        else:
            formatted_channel_id = str(channel_id)

        search_channel_id = int(formatted_channel_id)

        self.logger.info(
            f"Looking for discussion message for channel post {message_id}"
        )

        # Wait for the message to appear in the discussion group
        retry_count = 0
        max_retries = 30

        while retry_count < max_retries:
            # Query database for recent messages that might be our discussion message
            cursor = self.db_conn.cursor()
            cursor.execute(
                """
                SELECT raw_data
                FROM messages
                WHERE chat_id = ? AND created_at > datetime('now', '-5 minutes')
                ORDER BY created_at DESC
                LIMIT 20
            """,
                (self.chat_id,),
            )

            messages = cursor.fetchall()

            for msg_row in messages:
                try:
                    msg_data = json.loads(msg_row["raw_data"])

                    # Check if this is a forwarded message from our channel
                    if (
                        "message" in msg_data
                        and "forward_from_chat" in msg_data["message"]
                    ):
                        forward_info = msg_data["message"]["forward_from_chat"]
                        forward_msg_id = msg_data["message"].get(
                            "forward_from_message_id"
                        )
                        self.logger.debug(
                            f"forward_msg_id: {forward_msg_id}, forward_id: {forward_info.get('id')}, search_channel_id: {search_channel_id}, message_id: {message_id}"
                        )
                        # Check if this matches our original message
                        if (
                            forward_info.get("id") == search_channel_id
                            and forward_msg_id == message_id
                        ):
                            discussion_msg_id = msg_data["message"]["message_id"]
                            self.logger.info(
                                f"Found discussion message {discussion_msg_id} for channel post {message_id}"
                            )
                            return discussion_msg_id
                except Exception:
                    self.logger.exception("Error parsing message")
                    continue

            retry_count += 1
            time.sleep(3)

        self.logger.error(
            f"Could not find discussion message for channel message {message_id}"
        )
        return None

    def wait_for_forwarded_message(
        self, entity_type="channel", check_type=True, add_msg=None
    ):
        """
        Wait for the user to forward a message from a channel or chat to extract its ID.

        Args:
            entity_type (str): "channel" or "chat" - used for proper prompting
            check_type (bool): Whether to check if the forwarded message is from a channel

        Returns the numeric ID without the -100 prefix.
        """

        # Customize messages based on entity type
        if entity_type == "channel":
            entity_name = "channel"
            instruction_message = (
                "🔄 Please forward any message from the target channel"
            )
            success_message = "✅ Successfully extracted channel ID: {}"
            failure_message = "❌ Failed to extract channel ID."
        else:
            entity_name = "discussion group"
            instruction_message = (
                f"🔄 Please post to the discussion group a message with text: {self.chat_auth_uuid}\n\n"
                "⚠️ IMPORTANT: Bot should be added to the discussion group and have ADMIN rights!"
            )
            success_message = "✅ Successfully extracted discussion group ID: {}"
            failure_message = "❌ Failed to extract discussion group ID."

        if add_msg:
            instruction_message = add_msg + "\n\n" + instruction_message

        # Send instructions to the user
        self.send_api_request(
            "sendMessage",
            {"chat_id": self.control_chat_id, "text": instruction_message},
        )

        # Wait for a forwarded message
        resolved = False
        retry_count = 0
        max_retries = 30  # 5 minutes (10 seconds per retry)
        extracted_id = None

        # Extract channel ID for comparison if we're looking for a discussion group
        channel_numeric_id = None
        if (
            entity_type == "chat"
            and self.channel_id
            and str(self.channel_id).startswith("-100")
        ):
            channel_numeric_id = int(str(self.channel_id)[4:])

        while not resolved and retry_count < max_retries:
            time.sleep(10)  # Check every 10 seconds

            # Look for a forwarded message in recent messages
            cursor = self.db_conn.cursor()
            if self.created_at:
                threshold = "'" + self.created_at + "'"
            else:
                threshold = "datetime('now', '-2 minutes')"
            cursor.execute(
                f"""
                SELECT raw_data, created_at
                FROM messages
                WHERE created_at > {threshold}
                ORDER BY created_at DESC
            """
            )

            messages = cursor.fetchall()

            for row in messages:
                if self.args.debug:
                    self.logger.info(row["raw_data"])
                if self.created_at and row["created_at"] < self.created_at:
                    break
                msg_data = json.loads(row["raw_data"])
                if entity_type == "chat":
                    if get_text(msg_data) != self.chat_auth_uuid:
                        continue
                    extracted_id = msg_data["message"]["chat"]["id"]
                    if (
                        extracted_id == channel_numeric_id
                        or extracted_id == self.control_chat_id
                    ):
                        self.logger.warning(
                            "User posted a message in the channel, not the discussion group"
                        )
                        self.send_api_request(
                            "sendMessage",
                            {
                                "chat_id": self.control_chat_id,
                                "text": (
                                    "⚠️ You posted a message in the channel, not in the discussion group."
                                ),
                            },
                        )
                        # Skip this message and continue waiting
                        continue
                elif entity_type == "channel":
                    if "message" not in msg_data:
                        continue
                    if msg_data["message"]["chat"]["id"] != self.control_chat_id:
                        continue
                    if "forward_from_chat" in msg_data["message"]:
                        forward_info = msg_data["message"]["forward_from_chat"]

                        # Extract chat ID from the message
                        chat_id = forward_info.get("id")
                        # Remove -100 prefix if present
                        if str(chat_id).startswith("-100"):
                            extracted_id = int(str(chat_id)[4:])
                        else:
                            extracted_id = chat_id
                # For channels, check the type; for chats, accept any type except "channel" if check_type is False
                if extracted_id and (
                    (check_type and forward_info.get("type") == "channel")
                    or (not check_type)
                ):
                    resolved = True
                    self.created_at = row["created_at"]
                    self.logger.info(
                        f"Extracted {entity_name} ID: {extracted_id} from forwarded message"
                    )

                    # Send confirmation message
                    self.send_api_request(
                        "sendMessage",
                        {
                            "chat_id": self.control_chat_id,
                            "text": success_message.format(extracted_id),
                        },
                    )

                    return extracted_id

            retry_count += 1

            print(f"Waiting for forwarded message... ({retry_count}/{max_retries})")

        if not resolved:
            self.logger.error(
                f"Failed to extract {entity_name} ID from forwarded message"
            )
            self.send_api_request(
                "sendMessage",
                {"chat_id": self.control_chat_id, "text": failure_message},
            )
            return None

    def verify_access(self, telegram_id, hr_type=None):
        if not str(telegram_id).startswith("-100"):
            telegram_id = f"-100{telegram_id}"
        try:
            result = self.send_api_request(
                "getChatAdministrators", {"chat_id": telegram_id}
            )
            if self.args.debug:
                print(f"getChatAdministrators result: {result}")
            admin_ids = {x["user"]["id"] for x in result}
            return self.bot_id in admin_ids
        except Exception as e:
            raise ChgksuiteError(f"Bot isn't added to {hr_type}") from e
