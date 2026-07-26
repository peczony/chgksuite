#!/usr/bin/env python3
"""
Automatically generate documentation screenshots for chgksuite_qt.

Launches the Qt GUI, clicks through the different modes via macOS
accessibility / AppleScript, and captures each window state using
screencapture (with the native macOS window shadow).

Usage:
    uv run python scripts/generate_screenshots.py [--discover]

Prerequisites:
    - macOS only (uses osascript + screencapture)
    - The terminal / IDE running this script must have Accessibility
      permissions in System Settings > Privacy & Security > Accessibility.

Flags:
    --discover   Print the accessibility tree of the chgksuite window
                 and exit (useful for debugging).
"""

import os
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
IMAGES_DIR = os.path.join(
    PROJECT_ROOT, "chgksuite", "docs", "docs", "images"
)
WINDOW_TITLE_PREFIX = "chgksuite v"

# Delay (seconds) after each UI action to let the window resize / repaint.
UI_SETTLE = 0.6


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def osascript(script: str) -> str:
    """Run an AppleScript snippet.  Returns stdout; raises on failure."""
    r = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, check=False
    )
    if r.returncode != 0:
        raise RuntimeError(f"osascript failed: {r.stderr.strip()}")
    return r.stdout.strip()


def jxa(script: str) -> str:
    """Run a JXA (JavaScript for Automation) snippet. Returns stdout."""
    r = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"JXA failed: {r.stderr.strip()}")
    return r.stdout.strip()


def find_chgksuite_window():
    """Return (process_name, cg_window_id) using JXA + CoreGraphics.

    Matches by window title prefix.
    """
    result = jxa("""
ObjC.import("CoreGraphics");
ObjC.import("Foundation");
var windowList = $.CGWindowListCopyWindowInfo(
    $.kCGWindowListOptionOnScreenOnly, 0
);
var count = $.CFArrayGetCount(windowList);
var found = null;
for (var i = 0; i < count; i++) {
    var dict = ObjC.castRefToObject($.CFArrayGetValueAtIndex(windowList, i));
    var name = ObjC.unwrap(dict.objectForKey("kCGWindowName")) || "";
    if (name.indexOf("chgksuite v") === 0) {
        found = JSON.stringify({
            proc: ObjC.unwrap(dict.objectForKey("kCGWindowOwnerName")),
            wid: ObjC.unwrap(dict.objectForKey("kCGWindowNumber"))
        });
        break;
    }
}
found;
""")
    if not result or result == "null":
        return None, None
    import json
    data = json.loads(result)
    return data["proc"], int(data["wid"])


def wait_for_window(timeout: float = 20.0):
    """Block until the chgksuite window appears.  Returns (proc, wid)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc, wid = find_chgksuite_window()
        if proc and wid:
            # Bring to front
            osascript(
                f'tell application "System Events" to tell process "{proc}" '
                f"to set frontmost to true"
            )
            time.sleep(UI_SETTLE)
            return proc, wid
        time.sleep(0.5)
    raise TimeoutError("chgksuite window did not appear within timeout")


# ---------------------------------------------------------------------------
# Accessibility helpers  (AppleScript talks to System Events)
# ---------------------------------------------------------------------------

def _ax_click(proc: str, role: str, title: str):
    """Click the first accessibility element with *role* and *title*
    found anywhere inside window 1 of *proc*.

    Uses `entire contents` — slow but reliable for Qt widget hierarchies.
    """
    # Escape backslashes and quotes in title for AppleScript string
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "System Events"
    tell process "{proc}"
        set ec to entire contents of window 1
        repeat with elem in ec
            try
                if role of elem is "{role}" and title of elem is "{safe_title}" then
                    perform action "AXPress" of elem
                    return "ok"
                end if
            end try
        end repeat
    end tell
end tell
return "not_found"
'''
    result = osascript(script)
    if result == "not_found":
        raise RuntimeError(
            f'Could not find {role} titled "{title}" in the window'
        )


def click_radio(proc: str, title: str):
    _ax_click(proc, "AXRadioButton", title)
    time.sleep(UI_SETTLE)


def click_checkbox(proc: str, title: str, desired_state: bool = True):
    """Ensure a checkbox is in *desired_state* (True = checked)."""
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "System Events"
    tell process "{proc}"
        set ec to entire contents of window 1
        repeat with elem in ec
            try
                if role of elem is "AXCheckBox" and title of elem is "{safe_title}" then
                    set cur to value of elem
                    if cur is not {1 if desired_state else 0} then
                        perform action "AXPress" of elem
                    end if
                    return "ok"
                end if
            end try
        end repeat
    end tell
end tell
return "not_found"
'''
    result = osascript(script)
    if result == "not_found":
        raise RuntimeError(
            f'Could not find checkbox titled "{title}" in the window'
        )
    time.sleep(UI_SETTLE)


def set_combobox(proc: str, index: int, value: str):
    """Set the text of the Nth (1-based) editable combobox in the window.

    Focuses the text field inside the combobox, selects all, and types
    the new value via keystrokes.
    """
    safe_value = value.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "System Events"
    tell process "{proc}"
        set ec to entire contents of window 1
        set idx to 0
        repeat with elem in ec
            try
                if role of elem is "AXComboBox" then
                    set idx to idx + 1
                    if idx is {index} then
                        -- Focus the text field inside the combo box
                        set focused of text field 1 of elem to true
                        delay 0.2
                        -- Select all and type new value
                        keystroke "a" using command down
                        delay 0.1
                        keystroke "{safe_value}"
                        delay 0.1
                        return "ok"
                    end if
                end if
            end try
        end repeat
    end tell
end tell
return "not_found"
'''
    result = osascript(script)
    if result == "not_found":
        raise RuntimeError(
            f"Could not find combobox #{index} in the window"
        )
    time.sleep(UI_SETTLE)


def set_telegram_comboboxes(proc: str, channel: str, chat: str):
    """Set the telegram chat combobox value.

    The channel combobox already defaults to the first saved target.
    We Tab-navigate from the account text field (a reliable anchor)
    to reach the chat combobox, then type the value.

    Qt's accessibility on macOS has off-by-one bugs with ``set value``
    and ``set focused``, so Tab navigation is the only reliable method.
    """
    safe_chat = chat.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "System Events"
    tell process "{proc}"
        -- Focus the account text field (#1) as a reliable anchor
        set ec to entire contents of window 1
        set idx to 0
        repeat with elem in ec
            try
                if role of elem is "AXTextField" then
                    set idx to idx + 1
                    if idx is 1 then
                        set focused of elem to true
                        delay 0.1
                        exit repeat
                    end if
                end if
            end try
        end repeat
        -- Tab: account -> channel combobox -> chat combobox
        key code 48
        delay 0.1
        key code 48
        delay 0.1
        -- Select all and type chat value
        keystroke "a" using command down
        delay 0.1
        keystroke "{safe_chat}"
        delay 0.2
        -- Re-click the telegram radio to move focus away from text fields
        set ec2 to entire contents of window 1
        repeat with elem in ec2
            try
                if role of elem is "AXRadioButton" and title of elem is "telegram" then
                    perform action "AXPress" of elem
                    exit repeat
                end if
            end try
        end repeat
    end tell
end tell
'''
    osascript(script)
    time.sleep(UI_SETTLE)


# ---------------------------------------------------------------------------
# Screenshot capture
# ---------------------------------------------------------------------------

def capture(wid: int, filename: str):
    """Capture the window (with shadow) and save to IMAGES_DIR."""
    path = os.path.join(IMAGES_DIR, filename)
    subprocess.run(["screencapture", f"-l{wid}", path], check=True)
    print(f"  captured -> {filename}")


# ---------------------------------------------------------------------------
# Discovery / debug mode
# ---------------------------------------------------------------------------

def discover(proc: str):
    """Print a summary of all radio buttons and checkboxes in the window."""
    script = f'''
tell application "System Events"
    tell process "{proc}"
        set ec to entire contents of window 1
        set out to ""
        repeat with elem in ec
            try
                set r to role of elem
                if r is "AXRadioButton" or r is "AXCheckBox" then
                    set t to title of elem
                    set v to value of elem
                    set out to out & r & " | " & t & " | value=" & v & linefeed
                end if
            end try
        end repeat
    end tell
end tell
return out
'''
    print(osascript(script))


# ---------------------------------------------------------------------------
# Screenshot definitions
# ---------------------------------------------------------------------------

# Cyrillic string constants
ADVANCED_CHECKBOX = "\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u0434\u043e\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438"
# = "Показать дополнительные настройки"
TRELLO_DOWNLOAD = "\u0421\u043a\u0430\u0447\u0430\u0442\u044c \u0438\u0437 \u0422\u0440\u0435\u043b\u043b\u043e"
# = "Скачать из Трелло"
TRELLO_UPLOAD = "\u0417\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0432 \u0422\u0440\u0435\u043b\u043b\u043e"
# = "Загрузить в Трелло"

# Each entry: (filename, list_of_actions)
# Actions are tuples: ("radio", title) or ("checkbox", title, desired_state)
# Actions are applied in order; a capture follows each entry.

SCREENSHOTS = [
    # --- main window (nothing selected) ---
    ("main.png", []),

    # --- parse ---
    ("parse.png", [
        ("radio", "parse"),
    ]),

    # --- i14n_parse: parse + custom language + advanced settings ---
    ("i14n_parse.png", [
        ("radio", "parse"),
        ("radio", "custom"),
        ("checkbox", ADVANCED_CHECKBOX, True),
    ]),

    # --- compose > docx (Word) ---
    ("word.png", [
        ("checkbox", ADVANCED_CHECKBOX, False),
        ("radio", "compose"),
        ("radio", "docx"),
    ]),

    # --- i14n: compose > docx + custom language + advanced settings ---
    ("i14n.png", [
        ("radio", "compose"),
        ("radio", "docx"),
        ("radio", "custom"),
        ("checkbox", ADVANCED_CHECKBOX, True),
    ]),

    # --- compose > base ---
    ("base.png", [
        ("checkbox", ADVANCED_CHECKBOX, False),
        ("radio", "compose"),
        ("radio", "ru"),  # reset language from custom
        ("radio", "base"),
    ]),

    # --- compose > pptx ---
    ("pptx.png", [
        ("radio", "compose"),
        ("radio", "pptx"),
    ]),

    # --- compose > pptx + advanced settings ---
    ("pptx_additional_conf.png", [
        ("radio", "compose"),
        ("radio", "pptx"),
        ("checkbox", ADVANCED_CHECKBOX, True),
    ]),

    # --- compose > telegram ---
    ("telegram.png", [
        ("checkbox", ADVANCED_CHECKBOX, False),
        ("radio", "compose"),
        ("radio", "telegram"),
        # Both comboboxes default to the first saved target. Set them in
        # one shot so the calls don't interfere with each other.
        ("set_telegram_comboboxes", "chgksuite_tg_test_channel",
         "chgksuite_tg_test_channel_chat"),
    ]),

    # --- compose > lj ---
    ("lj.png", [
        ("radio", "compose"),
        ("radio", "lj"),
    ]),

    # --- compose > openquiz ---
    ("openquiz.png", [
        ("radio", "compose"),
        ("radio", "openquiz"),
    ]),

    # --- compose > add_stats ---
    ("stats.png", [
        ("radio", "compose"),
        ("radio", "add_stats"),
    ]),

    # --- trello > token ---
    ("trello_token.png", [
        ("radio", "trello"),
        ("radio", "token"),
    ]),

    # --- trello > download ---
    ("trello_download.png", [
        ("radio", "trello"),
        ("radio", TRELLO_DOWNLOAD),
    ]),

    # --- trello > upload ---
    ("trello_upload.png", [
        ("radio", "trello"),
        ("radio", TRELLO_UPLOAD),
    ]),

    # --- handouts > 4s -> hndt (generate) ---
    ("handouts_generate.png", [
        ("radio", "handouts"),
        ("radio", "4s \u2192 hndt"),
    ]),

    # --- handouts > hndt -> pdf (render) ---
    ("handouts_render.png", [
        ("radio", "handouts"),
        ("radio", "hndt \u2192 pdf"),
    ]),
]

# Screenshots that are NOT auto-generated (manual / external content):
SKIPPED = [
    "macos_security.png",   # macOS system dialog
    "openquiz2.png",        # Open-Quiz web UI screenshot
    "pptx_slide_q.png",     # PowerPoint slide content
    "pptx_slide_a.png",     # PowerPoint slide content
    "roenko.png",           # Web page screenshot
    "rozhdsushkov.png",     # Web page screenshot
    "douplet_problem.png",  # Not referenced in docs
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if sys.platform != "darwin":
        print("This script only works on macOS.")
        sys.exit(1)

    discover_mode = "--discover" in sys.argv

    # Launch the app
    print("Launching chgksuite_qt ...")
    app_proc = subprocess.Popen(
        [sys.executable, "-m", "chgksuite_qt"],
        cwd=PROJECT_ROOT,
    )

    try:
        proc, wid = wait_for_window()
        print(f"Found window: process={proc!r}, window_id={wid}")

        if discover_mode:
            print("\n--- Accessibility tree (radio buttons & checkboxes) ---")
            discover(proc)
            return

        print(f"\nGenerating {len(SCREENSHOTS)} screenshots into {IMAGES_DIR}")
        print(f"Skipping {len(SKIPPED)} non-automatable images\n")

        for filename, actions in SCREENSHOTS:
            print(f"[{filename}]")
            for action in actions:
                if action[0] == "radio":
                    print(f"    click radio: {action[1]}")
                    click_radio(proc, action[1])
                elif action[0] == "checkbox":
                    state = action[2]
                    verb = "check" if state else "uncheck"
                    print(f"    {verb} checkbox: {action[1]}")
                    click_checkbox(proc, action[1], state)
                elif action[0] == "combobox":
                    print(f"    set combobox #{action[1]} -> {action[2]}")
                    set_combobox(proc, action[1], action[2])
                elif action[0] == "set_telegram_comboboxes":
                    print(f"    set channel={action[1]}, chat={action[2]}")
                    set_telegram_comboboxes(proc, action[1], action[2])

            # Extra settle time for the window to resize
            time.sleep(UI_SETTLE)

            # Refresh window id in case it changed (unlikely but safe)
            _, wid_new = find_chgksuite_window()
            if wid_new:
                wid = wid_new
            capture(wid, filename)

        print(f"\nDone! {len(SCREENSHOTS)} screenshots generated.")
        print(f"Skipped (update manually): {', '.join(SKIPPED)}")

    finally:
        # Close the app
        print("\nClosing chgksuite_qt ...")
        app_proc.terminate()
        try:
            app_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            app_proc.kill()


if __name__ == "__main__":
    main()
