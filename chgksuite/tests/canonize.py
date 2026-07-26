import argparse
import inspect
import json
import os

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")
SKIP_FILES = {"tests_password.txt"}

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)

with open(os.path.join(currentdir, "settings.json")) as f:
    settings = json.loads(f.read())

from chgksuite_test import DefaultArgs

from chgksuite.common import read_text_file
from chgksuite.parser import (
    chgk_parse_docx,
    chgk_parse_txt,
    compose_4s,
    si_parse_docx,
    si_parse_text,
    troika_parse_docx,
    troika_parse_text,
)


def get_image_files():
    return {
        filename
        for filename in os.listdir(currentdir)
        if filename.lower().endswith(IMAGE_EXTENSIONS)
    }


def remove_added_images(before_images):
    for filename in get_image_files() - before_images:
        os.remove(os.path.join(currentdir, filename))


def workaround_chgk_parse(filename, game=None, **kwargs):
    args = DefaultArgs(**kwargs)
    if game in ("si", "troika"):
        if not getattr(args, "numbers_handling", None) or args.numbers_handling == "default":
            args.numbers_handling = "all"
        if filename.endswith(".docx"):
            if game == "si":
                return si_parse_docx(filename, args=args)
            return troika_parse_docx(filename, args=args)
        if filename.endswith(".txt"):
            if game == "si":
                return si_parse_text(read_text_file(filename), args=args)
            return troika_parse_text(read_text_file(filename), args=args)
        return None
    if filename.endswith(".txt"):
        return chgk_parse_txt(filename, args=args)
    if filename.endswith(".docx"):
        return chgk_parse_docx(filename, args=args)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parsing_engine", default="python_docx")
    parser.add_argument("file", nargs="?", help="Single file to canonize (optional)")
    args = parser.parse_args()

    if args.file:
        files = [args.file]
    else:
        files = os.listdir(currentdir)

    for filename in files:
        if filename.endswith((".docx", ".txt")) and filename not in SKIP_FILES:
            print(f"Canonizing {filename}...")
            images_before = get_image_files()
            file_settings = settings.get(filename, {})
            function_args = file_settings.get("function_args") or {}
            game = file_settings.get("game")
            parsed = workaround_chgk_parse(
                os.path.join(currentdir, filename),
                game=game,
                parsing_engine=args.parsing_engine,
                **function_args,
            )
            remove_added_images(images_before)
            compose_args = DefaultArgs()
            if game:
                compose_args.game = game
            if game in ("si", "troika"):
                compose_args.numbers_handling = "all"
            with open(
                os.path.join(currentdir, filename) + ".canon", "w", encoding="utf-8"
            ) as f:
                f.write(compose_4s(parsed, args=compose_args))


if __name__ == "__main__":
    main()
