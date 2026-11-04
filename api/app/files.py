"""Every disk operation the API does on the download share.

Rules, enforced here and nowhere else:
  * Only paths recorded in the job database are ever touched - there is no
    way to name an arbitrary file, and no directory listing.
  * The path must be inside DOWNLOAD_DIR with no symlink anywhere in it.
  * It must be a regular file owned by the user Fetcher runs as, whose
    device and inode still match what was recorded when Fetcher's download
    created it - and, once finished, whose size and modification time match
    too. (Inode numbers alone aren't enough: a freed inode is often reused
    right away by the next file created.) If anything doesn't match, the
    file was replaced or changed, and Fetcher refuses to touch it.
"""

import hashlib
import os
import re
import stat

from . import config

# Category = one subfolder of the share. Plain names only.
CATEGORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")


class FileRefused(Exception):
    pass


def _inside_share(path: str) -> str:
    root = os.path.realpath(config.DOWNLOAD_DIR)
    if not path or not os.path.isabs(path):
        raise FileRefused("no file recorded for this download")
    real = os.path.realpath(path)
    # realpath == normpath means no component is a symlink.
    if real != os.path.normpath(path) or not real.startswith(root + os.sep):
        raise FileRefused("file is outside the download folder or behind a symlink")
    return real


def identity(path: str) -> tuple[int, int, int, int] | None:
    """(dev, ino, size, mtime_ns) of a regular file of ours inside the share."""
    try:
        real = _inside_share(path)
        st = os.lstat(real)
    except (FileRefused, OSError):
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        return None
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


def verified(job: dict, finished: bool = False) -> str:
    """Return the job's file path if it is still the file Fetcher wrote.
    finished=True also requires the size and mtime recorded at completion."""
    real = _inside_share(job.get("path") or "")
    try:
        st = os.lstat(real)
    except FileNotFoundError:
        raise FileRefused("the file is no longer on disk")
    if not stat.S_ISREG(st.st_mode):
        raise FileRefused("not a regular file")
    if st.st_uid != os.getuid():
        raise FileRefused("the file belongs to another user, so Fetcher didn't write it (or PUID changed)")
    if job.get("file_ino") is None:
        raise FileRefused("Fetcher never saw this file being written, so it won't touch it")
    if (st.st_dev, st.st_ino) != (job["file_dev"], job["file_ino"]):
        raise FileRefused("the file was replaced since Fetcher downloaded it")
    if finished:
        if job.get("file_size") is None or job.get("file_mtime") is None:
            raise FileRefused("Fetcher has no record of this file as finished, so it won't touch it")
        if (st.st_size, st.st_mtime_ns) != (job["file_size"], job["file_mtime"]):
            raise FileRefused("the file was replaced or modified since Fetcher downloaded it")
    return real


def delete(job: dict, finished: bool = True) -> None:
    """Delete the job's file (and aria2's .aria2 resume file, if any)."""
    real = verified(job, finished)
    os.unlink(real)
    ctl = real + ".aria2"
    try:
        if stat.S_ISREG(os.lstat(ctl).st_mode):
            os.unlink(ctl)
    except FileNotFoundError:
        pass


def delete_partial(job: dict) -> None:
    """Like delete(), but a missing file is fine (nothing was written yet)."""
    try:
        delete(job, finished=False)
    except FileRefused as exc:
        if "no longer on disk" not in str(exc) and "no file recorded" not in str(exc):
            raise


def check_name(name: str) -> str:
    name = name.strip()
    if (not name or len(name.encode()) > 255 or name in (".", "..") or name.startswith(".")
            or "/" in name or "\\" in name or any(ord(c) < 32 for c in name)):
        raise FileRefused("not a valid file name")
    return name


def rename(job: dict, new_name: str) -> str:
    """Rename within the same folder. Never overwrites an existing file."""
    real = verified(job, finished=True)
    target = os.path.join(os.path.dirname(real), check_name(new_name))
    if os.path.lexists(target):
        raise FileRefused("a file with that name already exists")
    try:
        os.link(real, target)  # atomic: fails if target appeared meanwhile
        os.unlink(real)
    except OSError as exc:
        if os.path.lexists(target) and os.path.samefile(real, target):
            os.unlink(real)
        elif getattr(exc, "errno", None) in (1, 18, 95):  # EPERM/EXDEV/EOPNOTSUPP: no hard links
            os.rename(real, target)
        else:
            raise
    return target


def sha256(job: dict) -> str:
    real = verified(job, finished=True)
    h = hashlib.sha256()
    with open(real, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def category_dir(category: str) -> str:
    """The aria2 `dir` for a category; refuses names that could escape the share."""
    if not category:
        return config.DOWNLOAD_DIR
    if not CATEGORY_RE.match(category) or ".." in category:
        raise FileRefused("category names may use letters, digits, space, _ . - (max 64)")
    d = os.path.join(config.DOWNLOAD_DIR, category)
    if os.path.lexists(d):
        st = os.lstat(d)
        if not stat.S_ISDIR(st.st_mode):
            raise FileRefused(f"'{category}' exists in the download folder and is not a folder")
    return d


def disk() -> dict:
    try:
        st = os.statvfs(config.DOWNLOAD_DIR)
    except OSError:
        return {}
    return {"total": st.f_blocks * st.f_frsize, "free": st.f_bavail * st.f_frsize}
