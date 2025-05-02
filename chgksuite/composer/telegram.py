import json
import os
import random
import re
import sqlite3
import tempfile
import time
import uuid

import requests
import toml
from PIL import Image, ImageOps

from chgksuite.common import get_chgksuite_dir, init_logger, load_settings, tryint
from chgksuite.composer.composer_common import BaseExporter, parseimg
from chgksuite.composer.telegram_bot import run_bot_in_thread


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
        self.control_chat_id = None  # Chat ID where the user talks to the bot
        self.channel_id = None  # Target channel ID
        self.chat_id = None  # Discussion group ID linked to the channel
        self.auth_uuid = uuid.uuid4().hex[:8]
        self.init_telegram()

    def check_connectivity(self):
        req_me = requests.get(f"https://api.telegram.org/bot{self.bot_token}/getMe")
        if req_me.status_code != 200:
            raise Exception(
                f"getMe request wasn't successful: {req_me.status_code} {req_me.text}"
            )
        obj = req_me.json()
        assert obj["ok"]
        if self.args.debug:
            print(f"connection successful! {obj}")
        self.bot_id = obj["result"]["id"]

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
        self.bot_thread = run_bot_in_thread(self.bot_token, self.temp_db_path)
        cur = self.db_conn.cursor()
        while True:
            time.sleep(2)
            messages = cur.execute(
                "select raw_data, created_at from bot_status"
            ).fetchall()
            if messages and json.loads(messages[0][0])["status"] == "ok":
                break
        # Request user authentication
        self.authenticate_user()

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
            raise Exception("Authentication failed")

    def structure_has_stats(self):
        for element in self.structure:
            if element[0] == "Question" and "\nВзятия:" in element[1].get("comment"):
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
            raise Exception("don't publish questions without stats")

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

        try:
            if files:
                response = requests.post(url, data=data, files=files, timeout=60)
            else:
                response = requests.post(url, json=data, timeout=30)

            response_data = response.json()

            if not response_data.get("ok"):
                error_message = response_data.get("description", "Unknown error")
                self.logger.error(f"Telegram API error: {error_message}")

                # Handle rate limiting
                if "retry_after" in response_data:
                    retry_after = response_data["retry_after"]
                    self.logger.info(f"Rate limited. Waiting for {retry_after} seconds")
                    time.sleep(retry_after + 1)
                    return self.send_api_request(method, data, files)

                raise Exception(f"Telegram API error: {error_message}")

            return response_data["result"]
        except requests.exceptions.RequestException as e:
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
            if channel_id_str.startswith("-100"):
                channel_id_str = channel_id_str[4:]
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
                res += run[1]
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
                if run[1].startswith(("http://", "https://")):
                    res += run[1]
                else:
                    res += self.labels["general"].get("cf_image", "см. изображение")
                    parsed_image = parseimg(
                        run[1],
                        dimensions="ems",
                        targetdir=self.dir_kwargs.get("targetdir"),
                        tmp_dir=self.dir_kwargs.get("tmp_dir"),
                    )
                    imgfile = parsed_image["imgfile"]
                    if os.path.isfile(imgfile):
                        image = self.prepare_image_for_telegram(imgfile)
                    else:
                        raise Exception(f"image {run[1]} doesn't exist")
            else:
                raise Exception(f"unsupported tag `{run[0]}` in telegram export")
        while res.endswith("\n"):
            res = res[:-1]
        return res, image

    @classmethod
    def prepare_image_for_telegram(cls, imgfile):
        """Prepare an image for uploading to Telegram (resize if needed)."""
        img = Image.open(imgfile)
        width, height = img.size
        file_size = os.path.getsize(imgfile)
        modified = False

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
                img.convert("RGB").save(new_imgfile, "JPEG", quality=quality)
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
                    resized_img.convert("RGB").save(
                        new_imgfile, "JPEG", quality=quality
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
                result.append("{}. {}".format(i + 1, res_))
            res = "\n".join(result)
        return res, images

    def _post(self, chat_id, text, photo, reply_to_message_id=None):
        """Send a message to Telegram using API requests."""
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
            self.logger.error(f"Error posting message: {str(e)}")
            raise

    def post(self, posts):
        """Post a series of messages, handling the channel and discussion group."""
        if self.args.dry_run:
            self.logger.info("Skipping posting due to dry run")
            for post in posts:
                self.logger.info(post)
            return

        messages = []
        text, im = posts[0]

        # Step 1: Post the root message to the channel
        root_msg = self._post(
            self.channel_id,
            self.labels["general"]["handout_for_question"].format(text[3:])
            if text.startswith("QQQ")
            else text,
            im,
        )

        # Handle special case for questions with images
        if len(posts) >= 2 and text.startswith("QQQ") and im and posts[1][0]:
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
        """Wrapper for post() that handles section links."""
        messages = self.post(posts)
        if messages and self.section and not self.args.dry_run:
            self.section_links.append(
                self.get_message_link(self.channel_id, messages[0]["message_id"])
            )
        self.section = False

    def tg_process_element(self, pair):
        if pair[0] == "Question":
            q = pair[1]
            if "setcounter" in q:
                self.qcount = int(q["setcounter"])
            number = self.qcount if "number" not in q else q["number"]
            self.qcount += 1
            self.number = number
            if self.args.skip_until and (
                not tryint(number) or tryint(number) < self.args.skip_until
            ):
                self.logger.info(f"skipping question {number}")
                return
            if self.buffer_texts or self.buffer_images:
                posts = self.split_to_messages(self.buffer_texts, self.buffer_images)
                self.post_wrapper(posts)
                self.buffer_texts = []
                self.buffer_images = []
            posts = self.tg_format_question(pair[1], number=number)
            self.post_wrapper(posts)
        elif self.args.skip_until and (
            not tryint(self.number) or tryint(self.number) < self.args.skip_until
        ):
            self.logger.info(f"skipping element {pair[0]}")
            return
        elif pair[0] == "heading":
            text, images = self.tg_element_layout(pair[1])
            if not self.tg_heading:
                self.tg_heading = text
            self.buffer_texts.append(f"<b>{text}</b>")
            self.buffer_images.extend(images)
        elif pair[0] == "section":
            if self.buffer_texts or self.buffer_images:
                posts = self.split_to_messages(self.buffer_texts, self.buffer_images)
                self.post_wrapper(posts)
                self.buffer_texts = []
                self.buffer_images = []
            text, images = self.tg_element_layout(pair[1])
            self.buffer_texts.append(f"<b>{text}</b>")
            self.buffer_images.extend(images)
            self.section = True
        else:
            text, images = self.tg_element_layout(pair[1])
            if text:
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
            res = res[:-3] + "</tg-spoiler>"
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
            threshold = 2048
        if not texts:
            return "", im, texts, images
        if len(texts[0]) <= threshold:
            for i in range(0, len(texts)):
                if i:
                    text = self.assemble(texts[:-i])
                else:
                    text = self.assemble(texts)
                if len(text) <= threshold:
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
        result = []
        while texts or images:
            chunk, im, texts, images = self.make_chunk(texts, images)
            if chunk or im:
                result.append((chunk, im))
        return result

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

    def tg_format_question(self, q, number=None):
        txt_q, images_q = self.tgyapper(q["question"])
        txt_q = "<b>{}:</b> {}  \n".format(
            self.get_label(q, "question", number=number),
            txt_q,
        )
        if "number" not in q:
            self.qcount += 1
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
        q_threshold = 2048 if not images_q else 1024
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
        if len(full_question) <= q_threshold:
            res = [(full_question, images_q[0] if images_q else None)]
            for i in images_a:
                res.append(("", i))
            return res
        elif images_q and len(full_question) <= 2048:
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
        if len(q_without_s) <= q_threshold:
            res = [(q_without_s, images_q[0] if images_q else None)]
            res.extend(
                self.split_to_messages(
                    self.lwrap([self.swrap(txt_s), txt_au]), images_a
                )
            )
            return res
        q_a_only = self.assemble([txt_q, self.swrap(txt_a)], lb_after_first=True)
        if len(q_a_only) <= q_threshold:
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

    def export(self):
        """Main export function to send the structure to Telegram."""
        self.section_links = []
        self.buffer_texts = []
        self.buffer_images = []
        self.section = False

        if not self.args.tgchannel or not self.args.tgchat:
            raise Exception("Please provide channel and chat links or IDs.")

        # Try to extract IDs from links or direct ID inputs
        channel_result = self.extract_id_from_link(self.args.tgchannel)
        chat_result = self.extract_id_from_link(self.args.tgchat)

        # Handle channel resolution
        if isinstance(channel_result, int):
            channel_id = channel_result
        elif isinstance(channel_result, str):
            channel_id = self.resolve_username_to_id(channel_result)
            if not channel_id:
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
                    raise Exception("Failed to get channel ID from forwarded message")
        else:
            raise Exception("Channel ID is undefined")
        # Handle chat resolution
        if isinstance(chat_result, int):
            chat_id = chat_result
        elif isinstance(chat_result, str):
            chat_id = self.resolve_username_to_id(chat_result)
            if not chat_id:
                print("\n" + "=" * 50)
                print(
                    "Please forward any message from the discussion group to the bot."
                )
                print("This will allow me to extract the group ID automatically.")
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
                        "you forwarded a message from discussion group that itself was automatically forwarded "
                        "from the channel by Telegram. Please forward a message that was sent directly in the discussion group."
                    )
                    self.logger.error(error_msg)
                    chat_id = self.wait_for_forwarded_message(
                        entity_type="chat",
                        check_type=False,
                        add_msg=error_msg,
                    )
                if chat_id:
                    self.save_username(chat_result, chat_id)
        else:
            raise Exception("Chat ID is undefined")

        if not channel_id:
            raise Exception("Channel ID is undefined")
        if not chat_id:
            raise Exception("Chat ID is undefined")

        self.channel_id = f"-100{channel_id}"
        self.chat_id = f"-100{chat_id}"

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
            raise Exception(f"The bot doesn't have access to {' and '.join(bad)}")

        # Process all elements
        for pair in self.structure:
            self.tg_process_element(pair)

        # Handle any remaining buffer
        if self.buffer_texts or self.buffer_images:
            posts = self.split_to_messages(self.buffer_texts, self.buffer_images)
            self.post_wrapper(posts)
            self.buffer_texts = []
            self.buffer_images = []

        # Create and pin navigation message with links to sections
        if not self.args.skip_until:
            navigation_text = [self.labels["general"]["general_impressions_text"]]
            if self.tg_heading:
                navigation_text = [
                    f"<b>{self.tg_heading}</b>",
                    "",
                ] + navigation_text
            for i, link in enumerate(self.section_links):
                navigation_text.append(
                    f"{self.labels['general']['section']} {i + 1}: {link}"
                )
            navigation_text = "\n".join(navigation_text)

            # Post the navigation message
            if not self.args.dry_run:
                message = self._post(self.channel_id, navigation_text.strip(), None)

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
                except Exception as e:
                    self.logger.error(f"Failed to pin message: {str(e)}")
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
                        self.logger.info(
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
                except Exception as e:
                    self.logger.error(f"Error parsing message: {e}")
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
            instruction_message = "🔄 Please forward any message from the discussion group\n\n⚠️ IMPORTANT: Do NOT forward messages that were automatically posted from the channel. Forward messages that were sent directly in the discussion group."
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

        # Extract channel ID for comparison if we're looking for a discussion group
        channel_numeric_id = None
        if entity_type == "chat" and self.channel_id:
            if str(self.channel_id).startswith("-100"):
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
                if self.created_at and row["created_at"] < self.created_at:
                    break
                msg_data = json.loads(row["raw_data"])
                if msg_data["message"]["chat"]["id"] != self.control_chat_id:
                    continue
                if "message" in msg_data and "forward_from_chat" in msg_data["message"]:
                    forward_info = msg_data["message"]["forward_from_chat"]

                    # Extract chat ID from the message
                    chat_id = forward_info.get("id")
                    # Remove -100 prefix if present
                    if str(chat_id).startswith("-100"):
                        extracted_id = int(str(chat_id)[4:])
                    else:
                        extracted_id = chat_id

                    # If we're looking for a discussion group, verify it's not the same as the channel ID
                    if entity_type == "chat" and channel_numeric_id:
                        if extracted_id == channel_numeric_id:
                            self.logger.warning(
                                "User forwarded a message from the channel, not the discussion group"
                            )
                            self.send_api_request(
                                "sendMessage",
                                {
                                    "chat_id": self.control_chat_id,
                                    "text": "⚠️ You forwarded a message from the channel, not from the discussion group.\n\nPlease forward a message that was originally sent IN the discussion group, not an automatic repost from the channel.",
                                },
                            )
                            # Skip this message and continue waiting
                            continue

                    # For channels, check the type; for chats, accept any type except "channel" if check_type is False
                    if (check_type and forward_info.get("type") == "channel") or (
                        not check_type
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
        url = f"https://api.telegram.org/bot{self.bot_token}/getChatAdministrators"
        if not str(telegram_id).startswith("-100"):
            telegram_id = f"-100{telegram_id}"
        req = requests.post(url, data={"chat_id": telegram_id})
        if self.args.debug:
            print(req.status_code, req.text)
        if req.status_code != 200:
            raise Exception(f"Bot isn't added to {hr_type}")
        obj = req.json()
        admin_ids = {x["user"]["id"] for x in obj["result"]}
        return self.bot_id in admin_ids
