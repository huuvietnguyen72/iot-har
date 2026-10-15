from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import urllib.request
import uuid
import zipfile

import numpy as np

from .config import LABEL_MAP, UCI_URL, WINDOW_SIZE


@dataclass(frozen=True)
class WindowSet:
    windows: np.ndarray
    labels: np.ndarray
    subjects: np.ndarray
    source_rows: np.ndarray
    split: str
    excluded_rows: int = 0


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_split(root, split):
    if split not in ("train", "test"):
        raise ValueError("split must be train or test")
    folder = Path(root) / split
    signals = []
    for name in ("total_acc_x", "total_acc_y", "total_acc_z",
                 "body_gyro_x", "body_gyro_y", "body_gyro_z"):
        signal = np.loadtxt(folder / "Inertial Signals" / f"{name}_{split}.txt", ndmin=2)
        if signal.shape[1] != WINDOW_SIZE or not np.isfinite(signal).all():
            raise ValueError(f"invalid signal: {name}")
        signals.append(signal)
    labels = np.loadtxt(folder / f"y_{split}.txt", ndmin=1)
    subjects = np.loadtxt(folder / f"subject_{split}.txt", ndmin=1)
    n = len(labels)
    if labels.ndim != 1 or subjects.ndim != 1 or len(subjects) != n or not n:
        raise ValueError("invalid label/subject dimensions")
    if any(s.shape != (n, WINDOW_SIZE) for s in signals):
        raise ValueError("mismatched signal rows")
    for values in (labels, subjects):
        if not np.isfinite(values).all() or not np.equal(values, np.floor(values)).all():
            raise ValueError("labels and subjects must be finite integers")
    if not np.isin(labels, [1, 2, 3, 4, 5, 6]).all() or not ((subjects >= 1) & (subjects <= 30)).all():
        raise ValueError("unknown label or subject")
    keep = np.isin(labels, list(LABEL_MAP))
    windows = np.stack(signals, axis=2)[keep]
    return WindowSet(windows, np.array([LABEL_MAP[int(y)] for y in labels[keep]]),
                     subjects[keep].astype(int), np.flatnonzero(keep), split, int((~keep).sum()))


def _find_root(folder):
    roots = [p.parent for p in folder.rglob("activity_labels.txt")
             if (p.parent / "train").is_dir() and (p.parent / "test").is_dir()]
    if len(roots) != 1:
        raise ValueError("expected exactly one UCI dataset root")
    return roots[0]


def prepare_dataset(cache_dir, url=UCI_URL):
    cache = Path(cache_dir).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / "manifest.json"
    archive = cache / "archive.zip"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["source_url"] != url or sha256_file(archive) != manifest["archive_sha256"]:
            raise ValueError("dataset cache checksum or URL mismatch; use a fresh cache directory")
        root = (cache / manifest["dataset_root"]).resolve()
        if not root.is_relative_to(cache) or _find_root(root) != root:
            raise ValueError("invalid cached dataset root")
        return manifest
    if archive.exists():
        raise ValueError("unverified archive exists without manifest; use a fresh cache directory")
    part = cache / ("download-" + uuid.uuid4().hex + ".part")
    staging = cache / ("extracted-" + uuid.uuid4().hex)
    try:
        total = 0
        with urllib.request.urlopen(url, timeout=30) as source, part.open("xb") as target:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                target.write(block)
                total += len(block)
                if total % (8 * 1024 * 1024) == 0:
                    print(f"Downloaded {total // (1024 * 1024)} MiB", flush=True)
            expected = source.headers.get("Content-Length")
            if expected is not None and total != int(expected):
                raise ValueError("truncated dataset download")
        safe_extract(part, staging)
        try:
            root = _find_root(staging)
        except ValueError:
            nested = list(staging.rglob("*.zip"))
            if len(nested) != 1:
                raise ValueError("dataset wrapper must contain exactly one ZIP")
            safe_extract(nested[0], staging / "nested")
            root = _find_root(staging)
        manifest = {"source_url": url, "archive_sha256": sha256_file(part),
                    "download_bytes": total, "dataset_root": str(root.relative_to(cache)),
                    "attribution": "Reyes-Ortiz et al. (2013), UCI HAR, DOI 10.24432/C54S4K, CC BY 4.0"}
        part.rename(archive)
        with manifest_path.open("x", encoding="utf-8") as target:
            json.dump(manifest, target, indent=2)
        return manifest
    except Exception:
        part.unlink(missing_ok=True)
        if staging.exists():
            shutil.rmtree(staging)
        raise


def safe_extract(archive, destination):
    destination = Path(destination).resolve()
    try:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                path = PurePosixPath(name)
                if (path.is_absolute() or ".." in path.parts or ":" in name
                        or stat.S_ISLNK(info.external_attr >> 16)
                        or not (destination / name).resolve().is_relative_to(destination)):
                    raise ValueError("unsafe archive path")
            if z.testzip() is not None:
                raise ValueError("invalid ZIP checksum")
            destination.mkdir(parents=True, exist_ok=True)
            z.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid ZIP archive") from exc
