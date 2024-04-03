import importlib
import os
import random
import re
import time

import toml

from chgksuite.common import get_chgksuite_dir, init_logger, tryint
from chgksuite.composer.composer_common import BaseExporter, parseimg


class TelegramExporter(BaseExporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chgksuite_dir = get_chgksuite_dir()
        self.logger = kwargs.get("logger") or init_logger("composer")
        self.pyrogram = importlib.import_module(
            "pyrogram"
        )  # pyrogram slows down startup quite a bit, so only import it when needed
        try:
            self.init_tg()
        except self.pyrogram.errors.exceptions.unauthorized_401.AuthKeyUnregistered:
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
        self.app = self.pyrogram.Client(
            self.args.tgaccount,
            api_id,
            api_hash,
            workdir=self.chgksuite_dir,
            hide_password=not self.args.no_hide_password,
        )
        with self.app:
            self.logger.debug(self.app.get_me())

    def structure_has_stats(self):
        for element in self.structure:
            if element[0] == "Question" and "\nВзятия:" in element[1].get("comment"):
                return True
        return False

    def get_api_credentials(self):
        pyrogram_toml_file_path = os.path.join(self.chgksuite_dir, "pyrogram.toml")
        if os.path.exists(pyrogram_toml_file_path) and not self.args.reset_api:
            with open(pyrogram_toml_file_path, "r", encoding="utf8") as f:
                pyr = toml.load(f)
            if (
                pyr.get("stop_if_no_stats")
                and not self.structure_has_stats()
                and not os.environ.get("CHGKSUITE_BYPASS_STATS_CHECK")
            ):
                raise Exception("don't publish questions without stats")
            return pyr["api_id"], pyr["api_hash"]
        else:
            print("Please enter you api_id and api_hash.")
            print(
                "Go to https://my.telegram.org/apps, register an app and paste the credentials here."
            )
            api_id = input("Enter your api_id: ").strip()
            api_hash = input("Enter your api_hash: ").strip()
            with open(pyrogram_toml_file_path, "w", encoding="utf8") as f:
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

    def tgformat(self, s):
        res = ""
        image = None
        for run in self.parse_4s_elem(s):
            if run[0] in ("", "hyperlink"):
                res += run[1]
            if run[0] == "screen":
                res += run[1]["for_screen"]
            if run[0] == "strike":
                res += f"~~{run[1]}~~"
            if "italic" in run[0]:
                res += f"__{run[1]}__"
            if run[0] == "linebreak":
                res += "\n"
            if run[0] == "img":
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
                        image = imgfile
                    else:
                        raise Exception(f"image {run[1]} doesn't exist")
        while res.endswith("\n"):
            res = res[:-1]
        if "*" in res and not self.args.disable_asterisks_processing:
            res = res.replace("*", "&#42;")
        return res, image

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
        if photo:
            if not text:
                caption = ""
            elif text == "---":
                caption = "--"
            else:
                caption = "---"
            msg = self.app.send_photo(
                chat_id,
                photo,
                caption=caption,
                parse_mode=self.pyrogram.enums.ParseMode.MARKDOWN,
                reply_to_message_id=reply_to_message_id,
            )
            if text:
                time.sleep(2)
                self.app.edit_message_text(
                    chat_id,
                    msg.id,
                    text=text,
                    parse_mode=self.pyrogram.enums.ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
        else:
            msg = self.app.send_message(
                chat_id,
                text,
                parse_mode=self.pyrogram.enums.ParseMode.MARKDOWN,
                disable_web_page_preview=True,
                reply_to_message_id=reply_to_message_id,
            )
        return msg

    def __post(self, *args, **kwargs):
        retries = 0
        while retries <= 2:
            try:
                return self._post(*args, **kwargs)
            except self.pyrogram.errors.exceptions.flood_420.FloodWait as e:
                mstr = str(e)
                secs_to_wait = re.search("([0-9]+) seconds is required", mstr)
                if secs_to_wait:
                    secs_to_wait = int(secs_to_wait.group(1)) + 30
                else:
                    secs_to_wait = 120
                self.logger.error(
                    f"Telegram thinks we are spammers, waiting for {secs_to_wait} seconds"
                )
                time.sleep(secs_to_wait)
                retries += 1

    def post(self, posts):
        if self.args.dry_run:
            self.logger.info("skipping posting due to dry run")
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
        root_msg_in_chat = self.app.get_discussion_message(self.channel_id, root_msg.id)
        self.logger.info(
            f"Posted message {root_msg.link} ({root_msg_in_chat.link} in chat)"
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
                f"Replied to message {root_msg_in_chat.link} with {reply_msg.link}"
            )
            time.sleep(random.randint(5, 7))
            messages.append(reply_msg)
        return messages

    def post_wrapper(self, posts):
        messages = self.post(posts)
        if self.section and not self.args.dry_run:
            self.section_links.append(messages[0].link)
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
        elif self.args.skip_until and self.number < self.args.skip_until:
            self.logger.info(f"skipping element {pair[0]}")
            return
        elif pair[0] == "heading":
            text, images = self.tg_element_layout(pair[1])
            if not self.tg_heading:
                self.tg_heading = text
            self.buffer_texts.append(f"**{text}**")
            self.buffer_images.extend(images)
        elif pair[0] == "section":
            if self.buffer_texts or self.buffer_images:
                posts = self.split_to_messages(self.buffer_texts, self.buffer_images)
                self.post_wrapper(posts)
                self.buffer_texts = []
                self.buffer_images = []
            text, images = self.tg_element_layout(pair[1])
            self.buffer_texts.append(f"**{text}**")
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
        list_ = [x.strip() for x in list_ if not x.startswith("\n||")]
        if lb_after_first:
            list_[0] = list_[0] + "\n"
        res = "\n".join(list_)
        res = res.replace("\n||\n", "\n||")
        while res.endswith("\n"):
            res = res[:-1]
        if res.endswith("\n||"):
            res = res[:-3] + "||"
        if self.args.nospoilers:
            res = res.replace("||", "")
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
            if texts[0].endswith("||"):
                chunk += "||"
                rest = "||" + rest
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
            res = "||" + s_ + "||"
        elif t == "left":
            res = "||" + s_
        elif t == "right":
            res = s_ + "||"
        return res

    @staticmethod
    def lwrap(l_, lb_after_first=False):
        l_ = [x.strip() for x in l_ if x]
        if lb_after_first:
            return l_[0] + "\n" + "\n".join([x for x in l_[1:]])
        return "\n".join(l_)

    def tg_format_question(self, q, number=None):
        txt_q, images_q = self.tgyapper(q["question"])
        txt_q = "**{}:** {}  \n".format(
            self.get_label(q, "question", number=number),
            txt_q,
        )
        if "number" not in q:
            self.qcount += 1
        images_a = []
        txt_a, images_ = self.tgyapper(q["answer"])
        images_a.extend(images_)
        txt_a = "**{}:** {}".format(self.get_label(q, "answer"), txt_a)
        txt_z = ""
        txt_nz = ""
        txt_comm = ""
        txt_s = ""
        txt_au = ""
        if "zachet" in q:
            txt_z, images_ = self.tgyapper(q["zachet"])
            images_a.extend(images_)
            txt_z = "**{}:** {}".format(self.get_label(q, "zachet"), txt_z)
        if "nezachet" in q:
            txt_nz, images_ = self.tgyapper(q["nezachet"])
            images_a.extend(images_)
            txt_nz = "**{}:** {}".format(self.get_label(q, "nezachet"), txt_nz)
        if "comment" in q:
            txt_comm, images_ = self.tgyapper(q["comment"])
            images_a.extend(images_)
            txt_comm = "**{}:** {}".format(self.get_label(q, "comment"), txt_comm)
        if "source" in q:
            txt_s, images_ = self.tgyapper(q["source"])
            images_a.extend(images_)
            txt_s = f"**{self.get_label(q, 'source')}:** {txt_s}"
        if "author" in q:
            txt_au, images_ = self.tgyapper(q["author"])
            images_a.extend(images_)
            txt_au = f"**{self.get_label(q, 'author')}:** {txt_au}"
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
        with self.app:
            self.channel_dialog = None
            self.chat_dialog = None
            if (
                self.is_valid_tg_identifier(self.args.tgchannel)
                and self.is_valid_tg_identifier(self.args.tgchat)
            ):
                self.channel_id = self.is_valid_tg_identifier(self.args.tgchannel)
                self.chat_id = self.is_valid_tg_identifier(self.args.tgchat)
            else:
                for dialog in self.app.get_dialogs():
                    if (dialog.chat.title or "").strip() == self.args.tgchannel.strip():
                        self.channel_dialog = dialog
                    if (dialog.chat.title or "").strip() == self.args.tgchat.strip():
                        self.chat_dialog = dialog
                    if self.channel_dialog is not None and self.chat_dialog is not None:
                        break
                if not self.channel_dialog:
                    raise Exception("Channel not found, please check provided name")
                if not self.chat_dialog:
                    raise Exception("Linked chat not found, please check provided name")
                self.channel_id = self.channel_dialog.chat.id
                self.chat_id = self.chat_dialog.chat.id
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
                    navigation_text = [f"**{self.tg_heading}**", ""] + navigation_text
                for i, link in enumerate(self.section_links):
                    navigation_text.append(
                        f"{self.labels['general']['section']} {i + 1}: {link}"
                    )
                navigation_text = "\n".join(navigation_text)
                messages = self.post([(navigation_text.strip(), None)])
                if not self.args.dry_run:
                    self.app.pin_chat_message(
                        self.channel_id,
                        messages[0].id,
                        disable_notification=True,
                    )
