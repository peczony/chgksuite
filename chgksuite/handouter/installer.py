import functools
import os
import platform
import re
import shutil
import subprocess
import tarfile
import zipfile

import requests


def get_utils_dir():
    path = os.path.join(os.path.expanduser("~"), ".pecheny_utils")
    if not os.path.exists(path):
        os.mkdir(path)
    return path


def escape_latex(text):
    text = text.replace("\\", "\\textbackslash")
    text = text.replace("~", "\\textasciitilde")
    text = text.replace("^", "\\textasciicircum")
    for char in ("%", "&", "$", "#", "{", "}", "_"):
        text = text.replace(char, "\\" + char)
    text = text.replace("\n", "\\linebreak\n")
    return text


def check_tectonic_path(tectonic_path):
    proc = subprocess.run([tectonic_path, "--help"], capture_output=True, check=True)
    return proc.returncode == 0


def get_tectonic_path():
    errors = []
    system = platform.system()

    cpdir = get_utils_dir()
    if system == "Windows":
        binary_name = "tectonic.exe"
        tectonic_path = os.path.join(cpdir, binary_name)
    else:
        binary_name = "tectonic"
        tectonic_path = os.path.join(cpdir, binary_name)

    tectonic_ok = False
    try:
        tectonic_ok = check_tectonic_path(binary_name)
    except FileNotFoundError:
        pass  # tectonic not found in PATH
    except subprocess.CalledProcessError as e:
        errors.append(f"tectonic --version failed: {type(e)} {e}")
    if tectonic_ok:
        return binary_name
    if os.path.isfile(tectonic_path):
        try:
            tectonic_ok = check_tectonic_path(tectonic_path)
        except subprocess.CalledProcessError as e:
            errors.append(f"tectonic --version failed: {type(e)} {e}")
    if tectonic_ok:
        return tectonic_path


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


def parse_tectonic_archive_name(archive_name):
    if archive_name.endswith(".tar.gz"):
        archive_name = archive_name[: -len(".tar.gz")]
    elif archive_name.endswith(".zip"):
        archive_name = archive_name[: -len(".zip")]
    else:
        return
    sp = archive_name.split("-")
    result = {
        "version": sp[1],
        "arch": sp[2],
        "manufacturer": sp[3],
        "system": sp[4],
    }
    if len(sp) > 5:
        result["toolchain"] = sp[5]
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
    tf = tarfile.open(tar_file)
    tf.extractall(dirname)
    os.remove(tar_file)


def extract_archive(filename, dirname=None):
    if filename.lower().endswith((".tar", ".tar.gz")):
        extract_tar(filename, dirname=dirname)
    elif filename.lower().endswith(".zip"):
        extract_zip(filename, dirname=dirname)


def guess_archive_url(assets):
    system = platform.system()
    proc = platform.processor()
    if system == "Darwin":
        if proc == "arm" or (proc == "i386" and darwin_is_emulated()):
            arch = "aarch64"
        else:
            arch = "x86_64"
        for k, v in assets.items():
            parsed = parse_tectonic_archive_name(k)
            if not parsed:
                continue
            if parsed["arch"] == arch and parsed["system"] == "darwin":
                return v
    elif system == "Windows":
        for k, v in assets.items():
            parsed = parse_tectonic_archive_name(k)
            if not parsed:
                continue
            if (
                parsed["arch"] == "x86_64"
                and parsed["system"] == "windows"
                and parsed["toolchain"] == "msvc"
            ):
                return v
    elif system == "Linux":
        for k, v in assets.items():
            parsed = parse_tectonic_archive_name(k)
            if not parsed:
                continue
            if (
                (not proc or (proc and parsed["arch"] == proc))
                and parsed["system"] == "linux"
                and parsed["toolchain"] == "musl"
            ):
                return v
    raise Exception(f"Archive for system {system} proc {proc} not found")


def archive_url_from_regex(assets, regex):
    for k, v in assets.items():
        if re.match(regex, k):
            return v
    raise Exception(f"Archive for regex {regex} not found")


def install_tectonic(args):
    system = platform.system()
    assets = github_get_latest_release("tectonic-typesetting/tectonic")
    if args.tectonic_package_regex:
        archive_url = archive_url_from_regex(assets, args.tectonic_package_regex)
    else:
        archive_url = guess_archive_url(assets)
    downloaded = download_file(archive_url)
    dirname = "tectonic_folder"
    extract_archive(downloaded, dirname=dirname)
    if system == "Windows":
        filename = "tectonic.exe"
    else:
        filename = "tectonic"
    target_path = os.path.join(get_utils_dir(), filename)
    shutil.move(os.path.join(dirname, filename), target_path)
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
    raise Exception(f"{file_name} not found")


def install_font_from_github_wrapper(repo):
    latest = github_get_latest_release(repo)
    for k, v in latest.items():
        if k.endswith(".zip"):
            install_font(v)
            break
