#!/usr/bin/env python

import argparse
import builtins
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import urllib.request

try:
    from PyQt6 import QtGui, QtWidgets
    from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

    PYQT = True
except ImportError:
    PYQT = False

import shlex

from chgksuite.cli import ArgparseBuilder, single_action
from chgksuite.common import (
    DefaultNamespace,
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


def check_for_updates(channel="beta"):
    """Check PyPI for updates to chgksuite and chgksuite-qt.

    Returns (has_update, details_str, error, target_versions).
    """
    packages = ["chgksuite", "chgksuite-qt"]
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


class UpdateChecker(QObject):
    """Worker to check for updates in background thread."""

    finished = pyqtSignal(object, object, object, object)

    def __init__(self, channel="beta"):
        super().__init__()
        self.channel = channel

    def run(self):
        has_update, details, error, target_versions = check_for_updates(self.channel)
        self.finished.emit(has_update, details, error, target_versions)


LANGS = ["by", "by_tar", "en", "kz_cyr", "ru", "sr", "ua", "uz", "uz_cyr"] + ["custom"]

debug = False
ROW_SPACING_OBJECT_NAME = "rowSpacing"


class InputRequester(QObject):
    """Helper to request input from main thread via signal."""

    input_requested = pyqtSignal(str)

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.response = None
        self.event = threading.Event()
        self.input_requested.connect(self._show_dialog)

    def _show_dialog(self, prompt):
        text, ok = QtWidgets.QInputDialog.getText(
            self.parent_window, "Input Required", prompt
        )
        self.response = text if ok else ""
        self.event.set()

    def request_input(self, prompt=""):
        self.event.clear()
        self.response = None
        self.input_requested.emit(prompt)
        self.event.wait()  # Block until dialog is closed
        return self.response


class VarWrapper:
    def __init__(self, name, var):
        self.name = name
        self.var = var


class QString:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class RadioGroupVar:
    def __init__(self):
        self.radio_buttons = []

    def append(self, rb, value):
        self.radio_buttons.append((value, rb))

    def get(self):
        for val, rb in self.radio_buttons:
            if rb.isChecked():
                return val


def init_layout(frame, layout, spacing=0):
    layout.setSpacing(spacing)
    layout.setContentsMargins(spacing, spacing, spacing, spacing)


def add_row_spacing(layout, force=False):
    if not force and layout.count() == 0:
        return
    if layout.count() > 0:
        widget = layout.itemAt(layout.count() - 1).widget()
        if widget and widget.objectName() == ROW_SPACING_OBJECT_NAME:
            return
    spacer = QtWidgets.QWidget()
    spacer.setObjectName(ROW_SPACING_OBJECT_NAME)
    spacer.setFixedHeight(8)
    layout.addWidget(spacer)


class OpenFileDialog:
    def __init__(self, label, var, folder=False, lastdir=None, filetypes=None):
        self.label = label
        self.var = var
        self.folder = folder
        self.lastdir = lastdir
        self.filetypes = filetypes

    def __call__(self):
        if self.folder:
            output = QtWidgets.QFileDialog.getExistingDirectory(
                None, "Select Folder", self.lastdir or ""
            )
        else:
            output, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Select File",
                self.lastdir or "",
                ";;".join(
                    [
                        "{} ({})".format(ft[0], " ".join(ft[1]))
                        for ft in (self.filetypes or [])
                    ]
                ),
            )
        self.var.set(output or "")
        self.label.setText(os.path.basename(output or ""))


class ParserWrapper:
    def __init__(self, parser, parent=None, lastdir=None):
        self.parent = parent
        self.lastdir = lastdir if not parent else parent.lastdir
        if self.parent:
            self.parent.children.append(self)
            self.frame = QtWidgets.QWidget(self.parent.frame)
            self.layout = QtWidgets.QVBoxLayout(self.frame)
            init_layout(self.frame, self.layout)
            add_row_spacing(self.layout, force=True)
            self.parent.layout.addWidget(self.frame)
            self.frame.hide()
            self.advanced_frame = QtWidgets.QWidget(self.parent.advanced_frame)
            self.advanced_layout = QtWidgets.QVBoxLayout(self.advanced_frame)
            init_layout(self.advanced_frame, self.advanced_layout)
            self.parent.advanced_layout.addWidget(self.advanced_frame)
            self.advanced_frame.hide()
        else:
            self.init_qt()
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
                    to_append = [tup[0], str(tup[1])]
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
        self.output_text.clear()
        self.ok_button.setEnabled(False)

        # Capture stdout/stderr in a thread
        self.output_buffer = io.StringIO()
        self.output_buffer.write(self.cmdline_call_display + "\n")
        self.worker_done = False

        # Create input requester for GUI input dialogs
        self.input_requester = InputRequester(self.window)

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
            self.output_text.setPlainText(content)
            self.output_text.verticalScrollBar().setValue(
                self.output_text.verticalScrollBar().maximum()
            )
        if not self.worker_done:
            QTimer.singleShot(100, self.poll_output)
        else:
            self.ok_button.setEnabled(True)
            self.output_text.append("\n--- Готово ---")

    def toggle_advanced_frame(self):
        value = self.advanced_checkbox_var.isChecked()
        if value:
            self.advanced_frame.show()
        else:
            self.advanced_frame.hide()
        self.window.resize(self.window.minimumSizeHint())

    def check_and_update(self):
        """Check for updates and run self-update if available."""
        self.update_button.setEnabled(False)
        self.update_button.setText("Проверка обновлений...")

        channel = "stable" if self.stable_radio.isChecked() else "beta"

        self._update_thread = QThread()
        self._update_checker = UpdateChecker(channel)
        self._update_checker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_checker.run)
        self._update_checker.finished.connect(self._handle_update_check)
        self._update_checker.finished.connect(self._update_thread.quit)
        self._update_thread.start()

    def _handle_update_check(self, has_update, details, error, target_versions):
        """Handle update check result on main thread."""
        self.update_button.setEnabled(True)
        self.update_button.setText("Обновить chgksuite")
        self._target_versions = target_versions

        if has_update is None or (not has_update and not details):
            QtWidgets.QMessageBox.warning(
                self.window,
                "Ошибка",
                "Не удалось проверить обновления. Проверьте подключение к интернету.",
            )
            return

        if not has_update:
            QtWidgets.QMessageBox.information(
                self.window,
                "Обновления",
                f"Уже установлена последняя версия.\n\n{details}",
            )
            return

        # Update available - ask user
        reply = QtWidgets.QMessageBox.question(
            self.window,
            "Доступно обновление",
            f"Доступны обновления:\n{details}\n\n"
            "Обновить сейчас? Приложение будет закрыто.",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )

        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
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
            QtWidgets.QMessageBox.warning(
                self.window,
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
            self.app.quit()
        except Exception as e:
            logger.exception("could not launch the updater")
            QtWidgets.QMessageBox.critical(
                self.window, "Ошибка", f"Не удалось запустить обновление: {e}"
            )

    def init_qt(self):
        self.app = QtWidgets.QApplication(sys.argv)
        self.window = QtWidgets.QWidget()
        self.window.setWindowTitle(f"chgksuite v{__version__}")
        self.window_layout = QtWidgets.QVBoxLayout(self.window)
        init_layout(self.window, self.window_layout, spacing=10)
        self.frame = QtWidgets.QWidget()
        self.layout = QtWidgets.QVBoxLayout(self.frame)
        init_layout(self.frame, self.layout)
        self.button_frame = QtWidgets.QWidget()
        self.button_layout = QtWidgets.QVBoxLayout(self.button_frame)
        init_layout(self.button_frame, self.button_layout)
        self.advanced_frame = QtWidgets.QWidget()
        self.advanced_layout = QtWidgets.QVBoxLayout(self.advanced_frame)
        init_layout(self.advanced_frame, self.advanced_layout)
        self.window_layout.addWidget(self.frame)
        self.window_layout.addWidget(self.button_frame)
        self.window_layout.addWidget(self.advanced_frame)
        self.ok_button = QtWidgets.QPushButton("Запустить")
        self.ok_button.clicked.connect(self.ok_button_press)
        self.button_layout.addWidget(self.ok_button)
        self.advanced_checkbox_var = QtWidgets.QCheckBox(
            "Показать дополнительные настройки"
        )
        self.advanced_checkbox_var.stateChanged.connect(self.toggle_advanced_frame)
        self.button_layout.addWidget(self.advanced_checkbox_var)
        self.advanced_frame.hide()

        # Output text widget
        self.output_text = QtWidgets.QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QtGui.QFont("Courier", 10))
        self.output_text.setMinimumHeight(150)
        self.window_layout.addWidget(self.output_text)

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

            update_frame = QtWidgets.QWidget()
            update_layout = QtWidgets.QHBoxLayout(update_frame)
            init_layout(update_frame, update_layout)

            channel_label = QtWidgets.QLabel("Канал обновлений:")
            update_layout.addWidget(channel_label)

            default_channel = get_default_channel()
            self.channel_group = QtWidgets.QButtonGroup()
            self.stable_radio = QtWidgets.QRadioButton("Стабильный")
            self.beta_radio = QtWidgets.QRadioButton("Бета")
            self.channel_group.addButton(self.stable_radio)
            self.channel_group.addButton(self.beta_radio)
            if default_channel == "stable":
                self.stable_radio.setChecked(True)
            else:
                self.beta_radio.setChecked(True)
            update_layout.addWidget(self.stable_radio)
            update_layout.addWidget(self.beta_radio)

            self.update_button = QtWidgets.QPushButton("Обновить chgksuite")
            self.update_button.clicked.connect(self.check_and_update)
            update_layout.addWidget(self.update_button)

            self.window_layout.addWidget(update_frame)

    def add_argument(self, *args, **kwargs):
        if kwargs.pop("advanced", False):
            frame = self.advanced_frame
            layout = self.advanced_layout
        else:
            frame = self.frame
            layout = self.layout

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
            var = QString()
            var.set("false")
            innerframe = QtWidgets.QWidget(frame)
            innerlayout = QtWidgets.QHBoxLayout(innerframe)
            init_layout(innerframe, innerlayout)
            checkbutton = QtWidgets.QCheckBox(caption, innerframe)
            innerlayout.addWidget(checkbutton)
            layout.addWidget(innerframe)
            checkbutton.stateChanged.connect(
                lambda state, var=var: var.set("true" if state else "false")
            )
            self.vars.append(VarWrapper(name=args[0], var=var))

        elif argtype == "radiobutton":
            add_row_spacing(layout)
            var = QString()
            default = get_radiobutton_default(kwargs)
            var.set(default)
            innerframe = QtWidgets.QWidget(frame)
            innerlayout = QtWidgets.QHBoxLayout(innerframe)
            init_layout(innerframe, innerlayout)
            label = QtWidgets.QLabel(caption, innerframe)
            innerlayout.addWidget(label)
            button_group = QtWidgets.QButtonGroup(innerframe)
            for ch in kwargs["choices"]:
                radio = QtWidgets.QRadioButton(ch, innerframe)
                if ch == default:
                    radio.setChecked(True)
                button_group.addButton(radio)
                radio.toggled.connect(
                    lambda checked, var=var, ch=ch: var.set(ch) if checked else None
                )
                innerlayout.addWidget(radio)
            layout.addWidget(innerframe)
            self.vars.append(VarWrapper(name=args[0], var=var))

        elif argtype in {"filename", "folder"}:
            text = "(имя файла)" if argtype == "filename" else "(имя папки)"
            button_text = "Открыть файл" if argtype == "filename" else "Открыть папку"
            var = QString()
            innerframe = QtWidgets.QWidget(frame)
            innerlayout = QtWidgets.QHBoxLayout(innerframe)
            init_layout(innerframe, innerlayout)
            label = QtWidgets.QLabel(caption, innerframe)
            innerlayout.addWidget(label)
            label = QtWidgets.QLabel(text, innerframe)
            innerlayout.addWidget(label)
            button = QtWidgets.QPushButton(button_text, innerframe)
            button.clicked.connect(
                OpenFileDialog(
                    label,
                    var,
                    folder=argtype == "folder",
                    lastdir=self.lastdir,
                    filetypes=filetypes,
                )
            )
            innerlayout.addWidget(button)
            layout.addWidget(innerframe)
            self.vars.append(VarWrapper(name=args[0], var=var))

        elif argtype == "entry":
            var = QString()
            var.set(kwargs.get("default") or "")
            innerframe = QtWidgets.QWidget(frame)
            innerlayout = QtWidgets.QHBoxLayout(innerframe)
            init_layout(innerframe, innerlayout)
            label = QtWidgets.QLabel(caption, innerframe)
            innerlayout.addWidget(label)
            entry_show = "*" if "password" in args[0] else ""
            entry = QtWidgets.QLineEdit(innerframe)
            entry.setText(str(var.get()))
            if entry_show:
                entry.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
            innerlayout.addWidget(entry)
            layout.addWidget(innerframe)
            entry.textChanged.connect(var.set)
            self.vars.append(VarWrapper(name=args[0], var=var))

        elif argtype == "combobox":
            var = QString()
            default_val = kwargs.get("default") or ""
            innerframe = QtWidgets.QWidget(frame)
            innerlayout = QtWidgets.QHBoxLayout(innerframe)
            init_layout(innerframe, innerlayout)
            label = QtWidgets.QLabel(caption, innerframe)
            innerlayout.addWidget(label)
            combobox = QtWidgets.QComboBox(innerframe)
            combobox.setEditable(True)
            combobox.addItems(combobox_values)
            if default_val:
                combobox.setCurrentText(str(default_val))
            combobox.setMinimumWidth(200)
            innerlayout.addWidget(combobox)
            layout.addWidget(innerframe)
            combobox.currentTextChanged.connect(var.set)
            # Initialize var with current combobox text
            var.set(combobox.currentText())
            self.vars.append(VarWrapper(name=args[0], var=var))

        self.parser.add_argument(*args, **kwargs)

    def add_subparsers(self, *args, **kwargs):
        subparsers = self.parser.add_subparsers(*args, **kwargs)
        self.subparsers_var = RadioGroupVar()
        self.subparsers = SubparsersWrapper(subparsers, parent=self)
        return self.subparsers

    def show_frame(self):
        for child in self.parent.children:
            child.frame.hide()
            child.advanced_frame.hide()
        self.frame.show()
        self.advanced_frame.show()
        parent = self.parent
        while parent.parent:
            parent = parent.parent
        parent.window.resize(parent.window.minimumSizeHint())

    def parse_args(self, *args, **kwargs):
        argv = sys.argv[1:]
        if not argv:
            self.window.show()
            self.app.exec()
            # Window closed by user, exit cleanly
            sys.exit(0)
        return self.parser.parse_args(*args, **kwargs)


class SubparsersWrapper:
    def __init__(self, subparsers, parent):
        self.subparsers = subparsers
        self.parent = parent
        add_row_spacing(self.parent.layout)
        self.frame = QtWidgets.QWidget(self.parent.frame)
        self.parent.layout.addWidget(self.frame)
        self.parsers = []
        self.layout = QtWidgets.QHBoxLayout(self.frame)
        init_layout(self.frame, self.layout)

    def add_parser(self, *args, **kwargs):
        caption = kwargs.pop("caption", None) or args[0]
        parser = self.subparsers.add_parser(*args, **kwargs)
        pw = ParserWrapper(parser=parser, parent=self.parent)
        self.parsers.append(pw)
        radio = QtWidgets.QRadioButton(display_subparser_caption(caption), self.frame)
        self.parent.subparsers_var.append(radio, args[0])
        radio.toggled.connect(
            lambda checked, pw=pw: pw.show_frame() if checked else None
        )
        self.layout.addWidget(radio)
        return pw


def app():
    _, resourcedir = get_source_dirs()
    ld = get_lastdir()
    use_wrapper = len(sys.argv) == 1 and PYQT
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
