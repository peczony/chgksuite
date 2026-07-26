#!/usr/bin/env python

import argparse
import os
import subprocess
import sys
import urllib.request

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk

    TKINTER = True
except ImportError:
    TKINTER = False

import builtins
import io
import json
import logging
import re
import shlex
import threading

from chgksuite.cli import ArgparseBuilder, single_action
from chgksuite.common import (
    DefaultNamespace,
    ensure_utf8,
    get_lastdir,
    get_source_dirs,
)
from chgksuite.version import __version__

logger = logging.getLogger(__name__)


def is_app_translocated(path):
    """Check if the app is running from macOS App Translocation."""
    if sys.platform == "darwin" and path:
        return "/AppTranslocation/" in path
    return False


def get_pyapp_executable():
    """Return the pyapp executable path if running inside pyapp, else None."""
    pyapp_env = os.environ.get("PYAPP", "")
    # PYAPP_PASS_LOCATION sets PYAPP to the executable path instead of "1"
    if pyapp_env and pyapp_env != "1" and os.path.isfile(pyapp_env):
        return pyapp_env
    return None


def get_installed_version(package_name):
    """Get installed version of a package."""
    try:
        from importlib.metadata import version

        return version(package_name)
    except Exception:
        logger.exception(f"could not read installed version of {package_name}")
        return None


def _parse_pep440(v):
    """Parse PEP 440 version string into a sortable tuple."""
    m = re.match(
        r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:(a|b|rc)(\d+))?(?:\.post(\d+))?",
        v,
    )
    if not m:
        return (0,)
    major, minor, patch = int(m[1]), int(m[2] or 0), int(m[3] or 0)
    pre_order = {"a": -3, "b": -2, "rc": -1}
    pre = (pre_order.get(m[4], 0), int(m[5] or 0))
    post = int(m[6] or 0)
    return (major, minor, patch) + pre + (post,)


def check_pypi_version(package_name, channel="beta"):
    """Get latest version of a package from PyPI based on update channel."""
    try:
        url = f"https://pypi.org/pypi/{package_name}/json"
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            if channel == "stable":
                return data["info"]["version"]
            # Beta: find latest version including pre-releases
            versions = []
            for v, files in data["releases"].items():
                if files:  # only versions with uploaded files
                    try:
                        versions.append((_parse_pep440(v), v))
                    except Exception:
                        logger.exception(f"could not parse version {v}")
            if versions:
                versions.sort(key=lambda x: x[0])
                return versions[-1][1]
            return data["info"]["version"]
    except Exception:
        logger.exception(f"could not check PyPI version of {package_name}")
        return None


def get_default_channel():
    """Detect update channel based on installed version."""
    v = get_installed_version("chgksuite")
    if v and re.search(r"(a|b|rc|dev)\d*", v):
        return "beta"
    return "stable"


def display_subparser_caption(caption):
    m = re.match(r"^(.+)2(.+)$", caption)
    if m:
        return f"{m[1]} → {m[2]}"
    return caption


def get_radiobutton_default(kwargs):
    default = kwargs.get("default")
    if default is None:
        return kwargs["choices"][0]
    return default


def add_row_spacing(frame, force=False):
    children = frame.winfo_children()
    if not force and not children:
        return
    if children and getattr(children[-1], "_is_row_spacing", False):
        return
    spacer = tk.Frame(frame, height=8)
    spacer._is_row_spacing = True
    spacer.pack(side="top", fill="x")


def check_for_updates(channel="beta"):
    """Check PyPI for updates to chgksuite and chgksuite-tk.

    Returns (has_update, details_str, error, target_versions).
    """
    packages = ["chgksuite", "chgksuite-tk"]
    updates = []
    target_versions = {}

    for pkg in packages:
        installed = get_installed_version(pkg)
        latest = check_pypi_version(pkg, channel)
        if installed is None or latest is None:
            continue
        target_versions[pkg] = latest
        if installed != latest:
            updates.append((pkg, installed, latest))

    if updates:
        details = "\n".join(f"{pkg}: {inst} → {lat}" for pkg, inst, lat in updates)
        return True, details, None, target_versions

    # No updates - show current versions
    current = ", ".join(
        f"{pkg} {get_installed_version(pkg)}"
        for pkg in packages
        if get_installed_version(pkg)
    )
    return False, current, None, target_versions


class InputRequester:
    """Helper to request input from main thread via Tk dialog."""

    def __init__(self, tk_root):
        self.tk_root = tk_root
        self.response = None
        self.event = threading.Event()

    def _show_dialog(self, prompt):
        self.response = simpledialog.askstring(
            "Input Required", prompt, parent=self.tk_root
        )
        if self.response is None:
            self.response = ""
        self.event.set()

    def request_input(self, prompt=""):
        self.event.clear()
        self.response = None
        # Schedule dialog on main thread
        self.tk_root.after_idle(lambda: self._show_dialog(prompt))
        self.event.wait()  # Block until dialog is closed
        return self.response


class VarWrapper:
    def __init__(self, name, var):
        self.name = name
        self.var = var


class OpenFileDialog:
    def __init__(self, label, var, folder=False, lastdir=None, filetypes=None):
        self.label = label
        self.var = var
        self.folder = folder
        self.lastdir = lastdir
        self.filetypes = filetypes

    def __call__(self):
        function = (
            filedialog.askdirectory if self.folder else filedialog.askopenfilename
        )
        kwargs = {}
        if self.lastdir:
            kwargs["initialdir"] = self.lastdir
        if self.filetypes:
            kwargs["filetypes"] = self.filetypes
        output = function(**kwargs)
        if isinstance(output, bytes):
            output = output.decode("utf8")
        self.var.set(output or "")
        self.label.config(text=(output or "").split(ensure_utf8(os.sep))[-1])


class ParserWrapper:
    def __init__(self, parser, parent=None, lastdir=None):
        self.parent = parent
        if self.parent and not lastdir:
            self.lastdir = self.parent.lastdir
        else:
            self.lastdir = lastdir
        if self.parent:
            self.parent.children.append(self)
            self.frame = tk.Frame(self.parent.frame)
            add_row_spacing(self.frame, force=True)
            self.frame.pack()
            self.frame.pack_forget()
            self.advanced_frame = tk.Frame(self.parent.advanced_frame)
            self.advanced_frame.pack()
            self.advanced_frame.pack_forget()
        else:
            self.init_tk()
        self.parser = parser
        self.subparsers_var = None
        self.cmdline_call = None
        self.children = []
        self.vars = []

    def _list_vars(self):
        result = []
        for var in self.vars:
            result.append((var.name, var.var.get()))
        if self.subparsers_var:
            chosen_parser_name = self.subparsers_var.get()
            chosen_parser = next(
                x
                for x in self.subparsers.parsers
                if x.parser.prog.split()[-1] == chosen_parser_name
            )
            result.append(("", chosen_parser_name))
            result.extend(chosen_parser._list_vars())
        return result

    def build_command_line_call(self):
        result = []
        result_to_print = []
        for tup in self._list_vars():
            to_append = None
            if tup[0].startswith("--"):
                if tup[1] == "true":
                    to_append = tup[0]
                elif not tup[1] or tup[1] == "false":
                    continue
                else:
                    to_append = [tup[0], tup[1]]
            else:
                to_append = tup[1]
            if isinstance(to_append, list):
                result.extend(to_append)
                if "password" in tup[0]:
                    result_to_print.append(tup[0])
                    result_to_print.append("********")
                else:
                    result_to_print.extend(to_append)
            else:
                result.append(to_append)
                result_to_print.append(to_append)
        self.cmdline_call_display = f"Command line call: {shlex.join(result_to_print)}"
        print(self.cmdline_call_display)
        return result

    def ok_button_press(self):
        self.cmdline_call = self.build_command_line_call()
        if not self.cmdline_call:
            return

        # Clear output and disable button
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.config(state="disabled")
        self.ok_button.config(state="disabled")

        # Capture stdout/stderr in a thread
        self.output_buffer = io.StringIO()
        self.output_buffer.write(self.cmdline_call_display + "\n")
        self.worker_done = False

        # Create input requester for GUI input dialogs
        self.input_requester = InputRequester(self.tk)

        def worker():
            old_stdout, old_stderr = sys.stdout, sys.stderr
            old_input = builtins.input
            old_no_color = os.environ.get("NO_COLOR")
            sys.stdout = sys.stderr = self.output_buffer
            builtins.input = self.input_requester.request_input
            os.environ["NO_COLOR"] = "1"  # Disable ANSI colors in output
            try:
                _, resourcedir = get_source_dirs()
                args = DefaultNamespace(self.parser.parse_args(self.cmdline_call))
                single_action(args, False, resourcedir)
            except Exception:
                logger.exception("Error")
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr
                builtins.input = old_input
                if old_no_color is None:
                    os.environ.pop("NO_COLOR", None)
                else:
                    os.environ["NO_COLOR"] = old_no_color
                self.worker_done = True

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()
        self.poll_output()

    def poll_output(self):
        content = self.output_buffer.getvalue()
        if content:
            self.output_text.config(state="normal")
            self.output_text.delete("1.0", "end")
            self.output_text.insert("end", content)
            self.output_text.see("end")
            self.output_text.config(state="disabled")
        if not self.worker_done:
            self.tk.after(100, self.poll_output)
        else:
            self.ok_button.config(state="normal")
            self.output_text.config(state="normal")
            self.output_text.insert("end", "\n--- Готово ---\n")
            self.output_text.see("end")
            self.output_text.config(state="disabled")

    def toggle_advanced_frame(self):
        value = self.advanced_checkbox_var.get()
        if value == "true":
            self.advanced_frame.pack()
        else:
            self.advanced_frame.pack_forget()

    def check_and_update(self):
        """Check for updates and run self-update if available."""
        self.update_button.config(state="disabled", text="Проверка обновлений...")

        channel = self._channel_var.get()

        def check_thread():
            has_update, details, error, target_versions = check_for_updates(channel)
            self.tk.after(
                0,
                lambda: self._handle_update_check(
                    has_update, details, error, target_versions
                ),
            )

        threading.Thread(target=check_thread, daemon=True).start()

    def _handle_update_check(self, has_update, details, error, target_versions):
        """Handle update check result on main thread."""
        self.update_button.config(state="normal", text="Обновить chgksuite")
        self._target_versions = target_versions

        if has_update is None or (not has_update and not details):
            messagebox.showwarning(
                "Ошибка",
                "Не удалось проверить обновления. Проверьте подключение к интернету.",
            )
            return

        if not has_update:
            messagebox.showinfo(
                "Обновления", f"Уже установлена последняя версия.\n\n{details}"
            )
            return

        # Update available - ask user
        reply = messagebox.askyesno(
            "Доступно обновление",
            f"Доступны обновления:\n{details}\n\n"
            "Обновить сейчас? Приложение будет закрыто.",
        )

        if reply:
            self._run_self_update()

    def _build_pip_install_script(self):
        """Build a Python script that installs pinned package versions via pip."""
        pkgs = ", ".join(
            f"'{pkg}=={ver}'" for pkg, ver in self._target_versions.items()
        )
        return (
            "import subprocess, sys; "
            "subprocess.run([sys.executable, '-m', 'ensurepip', '--default-pip'], "
            "capture_output=True); "
            f"subprocess.run([sys.executable, '-m', 'pip', 'install', {pkgs}])"
        )

    def _run_self_update(self):
        """Run update and close the application."""
        if is_app_translocated(self.pyapp_executable):
            messagebox.showwarning(
                "Обновление невозможно",
                "Приложение запущено из временной папки (App Translocation).\n\n"
                "Чтобы обновить приложение:\n"
                "1. Закройте приложение\n"
                "2. Переместите его в папку «Программы» (Applications)\n"
                "3. Запустите приложение снова и нажмите «Обновить»",
            )
            return

        try:
            if self._target_versions and self._has_self_python:
                cmd = [
                    self.pyapp_executable,
                    "self",
                    "python",
                    "-c",
                    self._build_pip_install_script(),
                ]
            else:
                cmd = [self.pyapp_executable, "self", "update"]

            if sys.platform == "win32":
                subprocess.Popen(
                    cmd,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.DETACHED_PROCESS,
                    close_fds=True,
                )
            else:
                subprocess.Popen(
                    cmd,
                    start_new_session=True,
                    close_fds=True,
                )
            self.tk.quit()
        except Exception as e:
            logger.exception("could not launch the updater")
            messagebox.showerror("Ошибка", f"Не удалось запустить обновление: {e}")

    def init_tk(self):
        self.tk = tk.Tk()
        self.tk.title(f"chgksuite v{__version__}")
        self.tk.minsize(600, 400)
        self.tk.eval("tk::PlaceWindow . center")
        self.mainframe = tk.Frame(self.tk)
        self.mainframe.pack(side="top", fill="both", expand=True)
        self.frame = tk.Frame(self.mainframe)
        self.frame.pack(side="top")
        self.button_frame = tk.Frame(self.mainframe)
        self.button_frame.pack(side="top")
        self.ok_button = tk.Button(
            self.button_frame,
            text="Запустить",
            command=self.ok_button_press,
            width=15,
            height=2,
        )
        self.ok_button.pack(side="top")
        self.advanced_checkbox_var = tk.StringVar()
        self.toggle_advanced_checkbox = tk.Checkbutton(
            self.button_frame,
            text="Показать дополнительные настройки",
            onvalue="true",
            offvalue="false",
            variable=self.advanced_checkbox_var,
            command=self.toggle_advanced_frame,
        )
        self.toggle_advanced_checkbox.pack(side="top")
        self.advanced_frame = tk.Frame(self.mainframe)
        self.advanced_frame.pack(side="top")
        self.advanced_frame.pack_forget()

        # Output text widget
        self.output_frame = tk.Frame(self.mainframe)
        self.output_frame.pack(side="top", fill="both", expand=True, pady=10)
        self.output_text = tk.Text(
            self.output_frame, height=10, width=70, font=("Courier", 10)
        )
        self.output_scrollbar = tk.Scrollbar(
            self.output_frame, command=self.output_text.yview
        )
        self.output_text.configure(yscrollcommand=self.output_scrollbar.set)
        self.output_text.pack(side="left", fill="both", expand=True)
        self.output_scrollbar.pack(side="right", fill="y")
        self.output_text.config(state="disabled")

        # Update section (only shown when running inside pyapp)
        self.pyapp_executable = get_pyapp_executable()
        if self.pyapp_executable:
            # Check if self python is available (needs PYAPP_EXPOSE_PYTHON)
            try:
                r = subprocess.run(
                    [self.pyapp_executable, "self", "python", "--version"],
                    capture_output=True, timeout=5, check=False,
                )
                self._has_self_python = r.returncode == 0
            except Exception:
                logger.exception("could not probe pyapp self python")
                self._has_self_python = False
            self._target_versions = {}

            update_frame = tk.Frame(self.mainframe)
            update_frame.pack(side="top", pady=5)

            tk.Label(update_frame, text="Канал обновлений:").pack(side="left")

            default_channel = get_default_channel()
            self._channel_var = tk.StringVar(value=default_channel)

            tk.Radiobutton(
                update_frame, text="Стабильный",
                variable=self._channel_var, value="stable",
            ).pack(side="left")
            tk.Radiobutton(
                update_frame, text="Бета",
                variable=self._channel_var, value="beta",
            ).pack(side="left")

            self.update_button = tk.Button(
                update_frame,
                text="Обновить chgksuite",
                command=self.check_and_update,
            )
            self.update_button.pack(side="left", padx=(10, 0))

    def add_argument(self, *args, **kwargs):
        if kwargs.pop("advanced", False):
            frame = self.advanced_frame
        else:
            frame = self.frame
        if kwargs.pop("hide", False):
            self.parser.add_argument(*args, **kwargs)
            return
        caption = kwargs.pop("caption", None) or args[0]
        argtype = kwargs.pop("argtype", None)
        filetypes = kwargs.pop("filetypes", None)
        combobox_values = kwargs.pop("combobox_values", None) or []
        if not argtype:
            if kwargs.get("action") == "store_true":
                argtype = "checkbutton"
            elif args[0] in {"filename", "folder"}:
                argtype = args[0]
            else:
                argtype = "entry"
        if argtype == "checkbutton":
            var = tk.StringVar()
            var.set("false")
            innerframe = tk.Frame(frame)
            innerframe.pack(side="top")
            checkbutton = tk.Checkbutton(
                innerframe, text=caption, variable=var, onvalue="true", offvalue="false"
            )
            checkbutton.pack(side="left")
            self.vars.append(VarWrapper(name=args[0], var=var))
        elif argtype == "radiobutton":
            add_row_spacing(frame)
            var = tk.StringVar()
            var.set(get_radiobutton_default(kwargs))
            innerframe = tk.Frame(frame)
            innerframe.pack(side="top")
            label = tk.Label(innerframe, text=caption)
            label.pack(side="left")
            for ch in kwargs["choices"]:
                radio = tk.Radiobutton(
                    innerframe,
                    text=ch,
                    variable=var,
                    value=ch,
                )
                radio.pack(side="left")
            self.vars.append(VarWrapper(name=args[0], var=var))
        elif argtype in {"filename", "folder"}:
            text = "(имя файла)" if argtype == "filename" else "(имя папки)"
            button_text = "Открыть файл" if argtype == "filename" else "Открыть папку"
            var = tk.StringVar()
            innerframe = tk.Frame(frame)
            innerframe.pack(side="top")
            label = tk.Label(innerframe, text=caption)
            label.pack(side="left")
            label = tk.Label(innerframe, text=text)
            ofd_kwargs = {"folder": argtype == "folder", "lastdir": self.lastdir}
            if filetypes:
                ofd_kwargs["filetypes"] = filetypes
            button = tk.Button(
                innerframe,
                text=button_text,
                command=OpenFileDialog(label, var, **ofd_kwargs),
            )
            button.pack(side="left")
            label.pack(side="left")
            self.vars.append(VarWrapper(name=args[0], var=var))
        elif argtype == "entry":
            var = tk.StringVar()
            var.set(kwargs.get("default") or "")
            innerframe = tk.Frame(frame)
            innerframe.pack(side="top")
            tk.Label(innerframe, text=caption).pack(side="left")
            entry_show = "*" if "password" in args[0] else ""
            entry = tk.Entry(innerframe, textvariable=var, show=entry_show)
            entry.pack(side="left")
            self.vars.append(VarWrapper(name=args[0], var=var))

        elif argtype == "combobox":
            var = tk.StringVar()
            default_val = kwargs.get("default") or ""
            innerframe = tk.Frame(frame)
            innerframe.pack(side="top")
            tk.Label(innerframe, text=caption).pack(side="left")
            combobox = ttk.Combobox(
                innerframe, textvariable=var, values=combobox_values
            )
            combobox.pack(side="left")
            # Initialize with default or first item if available
            if default_val:
                var.set(default_val)
            elif combobox_values:
                var.set(combobox_values[0])
            self.vars.append(VarWrapper(name=args[0], var=var))

        self.parser.add_argument(*args, **kwargs)

    def add_subparsers(self, *args, **kwargs):
        subparsers = self.parser.add_subparsers(*args, **kwargs)
        self.subparsers_var = tk.StringVar()
        self.subparsers = SubparsersWrapper(subparsers, parent=self)
        return self.subparsers

    def show_frame(self):
        for child in self.parent.children:
            child.frame.pack_forget()
            child.advanced_frame.pack_forget()
        self.frame.pack(side="top")
        self.advanced_frame.pack(side="top")

    def parse_args(self, *args, **kwargs):
        argv = sys.argv[1:]
        if not argv:
            self.tk.mainloop()
            # Window closed by user, exit cleanly
            sys.exit(0)
        return self.parser.parse_args(*args, **kwargs)


class SubparsersWrapper:
    def __init__(self, subparsers, parent):
        self.subparsers = subparsers
        self.parent = parent
        add_row_spacing(self.parent.frame)
        self.frame = tk.Frame(self.parent.frame)
        self.frame.pack(side="top")
        self.parsers = []

    def add_parser(self, *args, **kwargs):
        caption = kwargs.pop("caption", None) or args[0]
        parser = self.subparsers.add_parser(*args, **kwargs)
        pw = ParserWrapper(parser=parser, parent=self.parent)
        self.parsers.append(pw)
        radio = tk.Radiobutton(
            self.frame,
            text=display_subparser_caption(caption),
            variable=self.parent.subparsers_var,
            value=args[0],
            command=pw.show_frame,
        )
        radio.pack(side="left")
        return pw


def app():
    _, resourcedir = get_source_dirs()
    ld = get_lastdir()
    use_wrapper = len(sys.argv) == 1 and TKINTER
    if use_wrapper:
        # GUI mode: window stays open, subprocess runs via ok_button_press()
        parser = argparse.ArgumentParser(prog="chgksuite")
        parser = ParserWrapper(parser, lastdir=ld)
        ArgparseBuilder(parser, use_wrapper).build()
        parser.parse_args()  # Shows window, runs event loop until closed
    else:
        # CLI mode: run directly
        parser = argparse.ArgumentParser(prog="chgksuite")
        ArgparseBuilder(parser, use_wrapper).build()
        args = DefaultNamespace(parser.parse_args())
        single_action(args, False, resourcedir)
