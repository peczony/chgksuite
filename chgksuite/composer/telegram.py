import importlib
import os
import random
import re
import sqlite3
import time

import toml
from PIL import Image, ImageOps
from telethon import errors
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import (
    GetDiscussionMessageRequest,
)
from telethon.tl.types import InputChannel

from chgksuite.common import get_chgksuite_dir, init_logger, load_settings, tryint
from chgksuite.composer.composer_common import BaseExporter, parseimg
from chgksuite.composer.telegram_parser import CustomHtmlParser


class TelegramExporter(BaseExporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chgksuite_dir = get_chgksuite_dir()
        self.logger = kwargs.get("logger") or init_logger("composer")
        try:
            self.init_tg()
        except (errors.AuthKeyUnregisteredError, sqlite3.OperationalError) as e:
            self.logger.warning(f"Session error: {str(e)}")
            filepath = os.path.join(
                self.chgksuite_dir, self.args.tgaccount + ".session"
            )
            if os.path.isfile(filepath):
                os.remove(filepath)
            self.init_tg()
        self.qcount = 1
        self.number = 1
        self.tg_heading = None

    def init_tg(self):
        api_id, api_hash = self.get_api_credentials()
        self.client = TelegramClient(
            os.path.join(self.chgksuite_dir, self.args.tgaccount), api_id, api_hash
        )
        self.client.start()
        me = self.client.get_me()
        self.logger.debug(f"Logged in as {me.username or me.first_name}")

    def structure_has_stats(self):
        for element in self.structure:
            if element[0] == "Question" and "\nВзятия:" in element[1].get("comment"):
                return True
        return False

    def get_message_link(self, message, channel=None):
        if not channel:
            channel = self.client.get_entity(message.peer_id)

        # Determine if the channel is public (has a username)
        if hasattr(channel, "username") and channel.username:
            # Public channel with username
            return f"https://t.me/{channel.username}/{message.id}"
        else:
            # Private channel, use channel ID
            channel_id_str = str(channel.id)
            # Remove -100 prefix if present (common in Telethon)
            if channel_id_str.startswith("-100"):
                channel_id_str = channel_id_str[4:]
            return f"https://t.me/c/{channel_id_str}/{message.id}"

    def get_api_credentials(self):
        settings = load_settings()
        telegram_toml_file_path = os.path.join(self.chgksuite_dir, "telegram.toml")
        if os.path.exists(telegram_toml_file_path) and not self.args.reset_api:
            with open(telegram_toml_file_path, "r", encoding="utf8") as f:
                tg = toml.load(f)
            if (
                settings.get("stop_if_no_stats")
                and not self.structure_has_stats()
                and not os.environ.get("CHGKSUITE_BYPASS_STATS_CHECK")
            ):
                raise Exception("don't publish questions without stats")
            return tg["api_id"], tg["api_hash"]
        else:
            print("Please enter you api_id and api_hash.")
            print(
                "Go to https://my.telegram.org/apps, register an app and paste the credentials here."
            )
            api_id = input("Enter your api_id: ").strip()
            api_hash = input("Enter your api_hash: ").strip()
            with open(telegram_toml_file_path, "w", encoding="utf8") as f:
                toml.dump({"api_id": api_id, "api_hash": api_hash}, f)
            return api_id, api_hash

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
        self.logger.info(f"Posting message `{text}`")
        if photo:
            if not text:
                caption = ""
            elif text == "---":
                caption = "--"
            else:
                caption = "---"
            msg = self.client.send_file(
                chat_id,
                photo,
                caption=caption,
                parse_mode=CustomHtmlParser,
                reply_to=reply_to_message_id,
                silent=True,
            )
            if text:
                time.sleep(2)
                msg = self.client.edit_message(
                    chat_id,
                    msg.id,
                    text=text,
                    parse_mode=CustomHtmlParser,
                    link_preview=False,
                )
        else:
            msg = self.client.send_message(
                chat_id,
                text,
                parse_mode=CustomHtmlParser,
                link_preview=False,
                reply_to=reply_to_message_id,
                silent=True,
            )
        return msg

    def __post(self, *args, **kwargs):
        retries = 0
        while retries <= 2:
            try:
                return self._post(*args, **kwargs)
            except errors.FloodWaitError as e:
                secs_to_wait = e.seconds + 30
                self.logger.error(
                    f"Telegram thinks we are spammers, waiting for {secs_to_wait} seconds"
                )
                time.sleep(secs_to_wait)
                retries += 1

    def post(self, posts):
        if self.args.dry_run:
            self.logger.info("skipping posting due to dry run")
            for post in posts:
                self.logger.info(post)
            return
        messages = []
        text, im = posts[0]
        root_msg = self.__post(
            self.channel_id,
            self.labels["general"]["handout_for_question"].format(text[3:])
            if text.startswith("QQQ")
            else text,
            im,
        )
        if (
            len(posts) >= 2 and text.startswith("QQQ") and im and posts[1][0]
        ):  # crutch for case when the question doesn't fit without image
            prev_root_msg = root_msg
            root_msg = self.__post(self.channel_id, posts[1][0], posts[1][1])
            posts = posts[1:]
            messages.append(root_msg)
            messages.append(prev_root_msg)
        time.sleep(2.1)

        result = self.client(
            GetDiscussionMessageRequest(peer=self.channel_entity, msg_id=root_msg.id)
        )
        root_msg_in_chat = result.messages[0]

        channel_username = getattr(self.channel_entity, "username", None)
        chat_username = getattr(self.chat_entity, "username", None)

        if channel_username:
            root_msg_link = f"https://t.me/{channel_username}/{root_msg.id}"
        else:
            root_msg_link = f"https://t.me/c/{str(self.channel_id)[4:]}/{root_msg.id}"

        if chat_username:
            root_msg_in_chat_link = (
                f"https://t.me/{chat_username}/{root_msg_in_chat.id}"
            )
        else:
            root_msg_in_chat_link = (
                f"https://t.me/c/{str(self.chat_id)[4:]}/{root_msg_in_chat.id}"
            )

        self.logger.info(
            f"Posted message {root_msg_link} ({root_msg_in_chat_link} in chat)"
        )
        time.sleep(random.randint(5, 7))
        if root_msg not in messages:
            messages.append(root_msg)
        messages.append(root_msg_in_chat)
        for post in posts[1:]:
            text, im = post
            reply_msg = self.__post(
                self.chat_id, text, im, reply_to_message_id=root_msg_in_chat.id
            )
            self.logger.info(
                f"Replied to message {root_msg_in_chat_link} with reply message"
            )
            time.sleep(random.randint(5, 7))
            messages.append(reply_msg)
        return messages

    def post_wrapper(self, posts):
        messages = self.post(posts)
        if self.section and not self.args.dry_run:
            self.section_links.append(self.get_message_link(messages[0]))
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
            if not x.startswith(("\n</spoiler>", "\n<spoiler>"))
        ]
        if lb_after_first:
            list_[0] = list_[0] + "\n"
        res = "\n".join(list_)
        res = res.replace("\n</spoiler>\n", "\n</spoiler>")
        res = res.replace("\n<spoiler>\n", "\n<spoiler>")
        while res.endswith("\n"):
            res = res[:-1]
        if res.endswith("\n</spoiler>"):
            res = res[:-3] + "</spoiler>"
        if self.args.nospoilers:
            res = res.replace("<spoiler>", "")
            res = res.replace("</spoiler>", "")
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
            if texts[0].endswith("</spoiler>"):
                chunk += "</spoiler>"
                rest = "<spoiler>" + rest
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
            res = "<spoiler>" + s_ + "</spoiler>"
        elif t == "left":
            res = "<spoiler>" + s_
        elif t == "right":
            res = s_ + "</spoiler>"
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
        self.section_links = []
        self.buffer_texts = []
        self.buffer_images = []
        self.section = False

        # Find channel and chat
        self.channel_entity = None
        self.chat_entity = None

        if self.is_valid_tg_identifier(
            self.args.tgchannel
        ) and self.is_valid_tg_identifier(self.args.tgchat):
            self.channel_id = self.is_valid_tg_identifier(self.args.tgchannel)
            self.chat_id = self.is_valid_tg_identifier(self.args.tgchat)
            self.channel_entity = InputChannel(self.channel_id, 0)
            self.chat_entity = InputChannel(self.chat_id, 0)
        else:
            # Get dialogs and find the channel and chat by title
            dialogs = self.client.get_dialogs()
            for dialog in dialogs:
                if (dialog.title or "").strip() == self.args.tgchannel.strip():
                    self.channel_entity = dialog.entity
                    self.channel_id = dialog.id
                if (dialog.title or "").strip() == self.args.tgchat.strip():
                    self.chat_entity = dialog.entity
                    self.chat_id = dialog.id
                if self.channel_entity is not None and self.chat_entity is not None:
                    break

            if not self.channel_entity:
                raise Exception("Channel not found, please check provided name")
            if not self.chat_entity:
                raise Exception("Linked chat not found, please check provided name")

        # Process all elements
        for pair in self.structure:
            self.tg_process_element(pair)

        if self.buffer_texts or self.buffer_images:
            posts = self.split_to_messages(self.buffer_texts, self.buffer_images)
            self.post_wrapper(posts)
            self.buffer_texts = []
            self.buffer_images = []

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
            messages = self.post([(navigation_text.strip(), None)])
            if not self.args.dry_run:
                self.client.pin_message(
                    self.channel_entity,
                    messages[0].id,
                    notify=False,
                )
