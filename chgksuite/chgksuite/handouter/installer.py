import functools
import os
import platform
import re
import shutil
import subprocess
import tarfile
import zipfile

import requests

from chgksuite.common import ChgksuiteError


def get_utils_dir():
    path = os.path.join(os.path.expanduser("~"), ".pecheny_utils")
    if not os.path.exists(path):
        os.mkdir(path)
    return path


def get_bundled_fonts_dir():
    """Directory of fonts shipped with the package (e.g. Noto Sans)."""
    from chgksuite.common import get_source_dirs

    _, resourcedir = get_source_dirs()
    return os.path.join(resourcedir, "fonts")


def escape_typst(text):
    r"""Escape user text so it renders literally in Typst markup mode.

    Only the characters that carry markup meaning are escaped; newlines become
    forced line breaks (``\`` followed by the newline).
    """
    text = text.replace("\\", "\\\\")
    for char in ("#", "$", "[", "]", "*", "_", "`", "<", ">", "@", "~"):
        text = text.replace(char, "\\" + char)
    # Neutralise comment sequences (`//`, `/* */`).
    text = text.replace("//", "\\/\\/").replace("/*", "\\/*").replace("*/", "*\\/")
    # A backslash immediately before a newline is a forced line break in Typst.
    text = text.replace("\n", "\\\n")
    return text


def check_typst_path(typst_path):
    proc = subprocess.run([typst_path, "--version"], capture_output=True, check=True)
    return proc.returncode == 0


def get_typst_path():
    errors = []
    system = platform.system()

    cpdir = get_utils_dir()
    if system == "Windows":
        binary_name = "typst.exe"
        typst_path = os.path.join(cpdir, binary_name)
    else:
        binary_name = "typst"
        typst_path = os.path.join(cpdir, binary_name)

    typst_ok = False
    try:
        typst_ok = check_typst_path(binary_name)
    except FileNotFoundError:
        pass  # typst not found in PATH
    except subprocess.CalledProcessError as e:
        errors.append(f"typst --version failed: {type(e)} {e}")
    if typst_ok:
        return binary_name
    if os.path.isfile(typst_path):
        try:
            typst_ok = check_typst_path(typst_path)
        except subprocess.CalledProcessError as e:
            errors.append(f"typst --version failed: {type(e)} {e}")
    if typst_ok:
        return typst_path


def github_get_latest_release(repo):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = requests.get(url)
    assets_url = req.json()["assets_url"]
    assets_req = requests.get(assets_url)
    return {asset["name"]: asset["browser_download_url"] for asset in assets_req.json()}


def darwin_is_emulated():
    try:
        sub = subprocess.run(
            ["sysctl", "-n", "sysctl.proc_translated"], capture_output=True, check=True
        )
        out = sub.stdout.decode("utf8").strip()
        return int(out)
    except subprocess.CalledProcessError:
        print("couldn't tell if emulated, returning 0")
        return 0


def parse_typst_archive_name(archive_name):
    """Parse a typst release asset name such as
    ``typst-x86_64-unknown-linux-musl.tar.xz`` into its components.
    """
    for suffix in (".tar.xz", ".tar.gz", ".zip"):
        if archive_name.endswith(suffix):
            archive_name = archive_name[: -len(suffix)]
            break
    else:
        return
    sp = archive_name.split("-")
    if len(sp) < 4 or sp[0] != "typst":
        return
    result = {
        "arch": sp[1],
        "manufacturer": sp[2],
        "system": sp[3],
    }
    if len(sp) > 4:
        result["toolchain"] = sp[4]
    return result


# download_file function taken from https://stackoverflow.com/a/39217788
def download_file(url):
    print(f"downloading from {url}...")
    local_filename = url.split("/")[-1]
    with requests.get(url, stream=True) as resp:
        resp.raw.read = functools.partial(resp.raw.read, decode_content=True)
        with open(local_filename, "wb") as f:
            shutil.copyfileobj(resp.raw, f, length=16 * 1024 * 1024)
    return local_filename


def extract_zip(zip_file, dirname=None):
    if dirname is None:
        dirname = zip_file[:-4]
    with zipfile.ZipFile(zip_file, "r") as zip_ref:
        zip_ref.extractall(dirname)
    os.remove(zip_file)


def extract_tar(tar_file, dirname=None):
    if dirname is None:
        dirname = tar_file[: tar_file.lower().index(".tar")]
    with tarfile.open(tar_file) as tf:
        tf.extractall(dirname)
    os.remove(tar_file)


def extract_archive(filename, dirname=None):
    if filename.lower().endswith((".tar", ".tar.gz", ".tar.xz")):
        extract_tar(filename, dirname=dirname)
    elif filename.lower().endswith(".zip"):
        extract_zip(filename, dirname=dirname)


def _machine_arch():
    machine = (platform.machine() or "").lower()
    if machine in ("arm64", "aarch64"):
        return "aarch64"
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    return machine


def guess_archive_url(assets):
    system = platform.system()
    if system == "Darwin":
        if _machine_arch() == "aarch64" or darwin_is_emulated():
            arch = "aarch64"
        else:
            arch = "x86_64"
        target_system, toolchain = "darwin", None
    elif system == "Windows":
        arch = _machine_arch() or "x86_64"
        target_system, toolchain = "windows", "msvc"
    elif system == "Linux":
        arch = _machine_arch() or "x86_64"
        target_system, toolchain = "linux", "musl"
    else:
        raise ChgksuiteError(f"Unsupported system {system}")

    for k, v in assets.items():
        parsed = parse_typst_archive_name(k)
        if not parsed:
            continue
        if parsed["arch"] != arch or parsed["system"] != target_system:
            continue
        if toolchain and parsed.get("toolchain") != toolchain:
            continue
        return v
    raise ChgksuiteError(f"typst archive for system {system} arch {arch} not found")


def archive_url_from_regex(assets, regex):
    for k, v in assets.items():
        if re.match(regex, k):
            return v
    raise ChgksuiteError(f"Archive for regex {regex} not found")


def _find_binary(root_dir, filename):
    for dir_, _, files in os.walk(root_dir):
        if filename in files:
            return os.path.join(dir_, filename)
    raise FileNotFoundError(f"{filename} not found in extracted archive {root_dir}")


def install_typst(args):
    system = platform.system()
    assets = github_get_latest_release("typst/typst")
    regex = getattr(args, "typst_package_regex", None)
    if regex:
        archive_url = archive_url_from_regex(assets, regex)
    else:
        archive_url = guess_archive_url(assets)
    downloaded = download_file(archive_url)
    dirname = "typst_folder"
    extract_archive(downloaded, dirname=dirname)
    filename = "typst.exe" if system == "Windows" else "typst"
    # The binary lives inside a per-target subfolder (e.g. typst-<triple>/typst).
    extracted_binary = _find_binary(dirname, filename)
    target_path = os.path.join(get_utils_dir(), filename)
    shutil.move(extracted_binary, target_path)
    if not os.access(target_path, os.X_OK):
        os.chmod(target_path, 0o755)
    shutil.rmtree(dirname)
    return target_path


def install_font(url):
    fn = url.split("/")[-1].split("?")[0]
    bn, ext = os.path.splitext(fn)
    if "." in bn:
        new_fn = bn.replace(".", "_") + ext
    else:
        new_fn = fn
    dir_name = new_fn[:-4]
    dir_name_base = dir_name.split(os.pathsep)[-1]
    fonts_dir = os.path.join(get_utils_dir(), "fonts")
    if not os.path.exists(fonts_dir):
        os.makedirs(fonts_dir)
    target_dir = os.path.join(fonts_dir, dir_name_base)
    if os.path.isdir(target_dir):
        print(f"{target_dir} already exists")
        return
    download_file(url)
    if fn != new_fn:
        os.rename(fn, new_fn)
    extract_archive(new_fn, dirname=dir_name)
    if not os.path.isdir(target_dir):
        shutil.copytree(dir_name, target_dir)
    shutil.rmtree(dir_name)


def find_font(file_name, root_dir=None):
    root_dir = root_dir or os.path.join(get_utils_dir(), "fonts")
    if not os.path.isdir(root_dir):
        os.makedirs(root_dir, exist_ok=True)
    for dir_, _, files in os.walk(root_dir):
        for fn in files:
            if fn == file_name:
                return os.path.join(dir_, fn)
    raise FileNotFoundError(f"{file_name} not found")


def install_font_from_github_wrapper(repo):
    latest = github_get_latest_release(repo)
    for k, v in latest.items():
        if k.endswith(".zip"):
            install_font(v)
            break
