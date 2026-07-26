#!/usr/bin/env python3
"""Print markdown download links for the latest GitHub release assets."""

import json
import subprocess
import sys

REPO = "peczony/chgksuite"

LABELS = {
    "windows-x64": "Windows x64",
    "macos-x64": "macOS с процессором Intel",
    "macos-arm64": "macOS с процессором Apple (M1 и новее)",
    "linux-x64": "Linux AMD64",
    "linux-arm64": "Linux ARM64",
}

PLATFORMS = ["windows-x64", "macos-x64", "macos-arm64", "linux-x64", "linux-arm64"]

APPS = [("chgkq", "Версия Qt"), ("chgkt", "Версия Tk")]


def main():
    result = subprocess.run(
        ["gh", "release", "view", "--repo", REPO, "--json", "assets"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    assets = {a["name"]: a["url"] for a in json.loads(result.stdout)["assets"]}

    for app, title in APPS:
        print(f"**{title}:**")
        for platform in PLATFORMS:
            for name, url in assets.items():
                if name.startswith(f"{app}-{platform}"):
                    print(f"- [{LABELS[platform]}]({url})")
                    break
        print()


if __name__ == "__main__":
    main()
