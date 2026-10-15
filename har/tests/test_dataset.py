import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

import numpy as np

from har.dataset import load_split, prepare_dataset, safe_extract
from har.tests.fixtures import uci_fixture


class DatasetTests(unittest.TestCase):
    def test_mapping_channel_order_and_exclusions(self):
        with TemporaryDirectory() as tmp:
            ds = load_split(uci_fixture(Path(tmp) / "uci"), "train")
            self.assertEqual(ds.labels.tolist(), ["walk", "sit", "stand", "lie"])
            self.assertEqual(ds.source_rows.tolist(), [0, 3, 4, 5])
            self.assertEqual(ds.excluded_rows, 2)
            self.assertEqual(ds.windows.shape, (4, 128, 6))
            np.testing.assert_equal(ds.windows[0, 0], [1, 2, 3, 4, 5, 6])

    def test_bad_samples_rows_and_nonfinite(self):
        for bad in (np.zeros((6, 127)), np.zeros((5, 128)), np.full((6, 128), np.nan)):
            with self.subTest(shape=bad.shape), TemporaryDirectory() as tmp:
                root = uci_fixture(Path(tmp) / "uci")
                np.savetxt(root / "train/Inertial Signals/total_acc_x_train.txt", bad)
                with self.assertRaises(ValueError):
                    load_split(root, "train")

    def test_bad_labels_and_subjects(self):
        for name, values in (("y", [1, 2, 3, 4, 5, 9]),
                             ("subject", [1, 1, 1.5, 1, 1, 1])):
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                root = uci_fixture(Path(tmp) / "uci")
                np.savetxt(root / "train" / f"{name}_train.txt", values)
                with self.assertRaises(ValueError):
                    load_split(root, "train")

    def test_download_cache_and_corruption(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = uci_fixture(tmp / "source")
            archive = tmp / "source.zip"
            with zipfile.ZipFile(archive, "w") as z:
                for path in root.rglob("*"):
                    if path.is_file():
                        z.write(path, Path("UCI HAR Dataset") / path.relative_to(root))
            cache = tmp / "cache"
            manifest = prepare_dataset(cache, url=archive.as_uri())
            self.assertEqual(len(manifest["archive_sha256"]), 64)
            self.assertEqual(prepare_dataset(cache, url=archive.as_uri()), manifest)
            self.assertEqual(load_split(cache / manifest["dataset_root"], "test").windows.shape, (4, 128, 6))
            (cache / "archive.zip").write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                prepare_dataset(cache, url=archive.as_uri())

    def test_nested_archive(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = uci_fixture(tmp / "source")
            inner = io.BytesIO()
            with zipfile.ZipFile(inner, "w") as z:
                for p in root.rglob("*"):
                    if p.is_file():
                        z.write(p, Path("UCI HAR Dataset") / p.relative_to(root))
            outer = tmp / "outer.zip"
            with zipfile.ZipFile(outer, "w") as z:
                z.writestr("UCI HAR Dataset.zip", inner.getvalue())
            manifest = prepare_dataset(tmp / "cache", url=outer.as_uri())
            self.assertTrue((tmp / "cache" / manifest["dataset_root"] / "activity_labels.txt").exists())

    def test_traversal_rejected_without_partial_extraction(self):
        for name in ("../escape.txt", "/absolute.txt", "C:/escape.txt", "..\\escape.txt"):
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                archive = Path(tmp) / "bad.zip"
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr("ok.txt", "ok")
                    z.writestr(name, "bad")
                with self.assertRaises(ValueError):
                    safe_extract(archive, Path(tmp) / "out")
                self.assertFalse((Path(tmp) / "out/ok.txt").exists())

    def test_invalid_archive_does_not_publish_manifest(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "bad.zip"
            source.write_bytes(b"not a zip")
            with self.assertRaises(ValueError):
                prepare_dataset(tmp / "cache", url=source.as_uri())
            self.assertFalse((tmp / "cache/manifest.json").exists())
