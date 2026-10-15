import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from har.artifact import load_bundle, save_bundle
from har.features import extract_features
from har.tests.fixtures import grouped_fixture


class ArtifactTests(unittest.TestCase):
    def make_model(self):
        ds = grouped_fixture([1, 2])
        f = extract_features(ds.windows)
        model = RandomForestClassifier(n_estimators=20, random_state=0).fit(f, ds.labels)
        return model, f

    def test_roundtrip_and_no_overwrite(self):
        model, f = self.make_model()
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            save_bundle(run, model, {"source": "synthetic test fixture"})
            restored, meta = load_bundle(run)
            np.testing.assert_array_equal(model.predict(f), restored.predict(f))
            self.assertEqual(len(meta["feature_names"]), 70)
            with self.assertRaises(FileExistsError):
                save_bundle(run, model, {})

    def test_schema_version_and_hash_rejected(self):
        model, _ = self.make_model()
        for mutation in ("schema", "versions", "hash"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as tmp:
                run = Path(tmp)
                save_bundle(run, model, {})
                meta = json.loads((run / "metadata.json").read_text())
                if mutation == "schema":
                    meta["feature_names"] = ["wrong"]
                elif mutation == "versions":
                    meta["versions"]["scikit-learn"] = "0.0"
                else:
                    (run / "model.joblib").write_bytes(b"broken")
                (run / "metadata.json").write_text(json.dumps(meta))
                with self.assertRaises(ValueError):
                    load_bundle(run)
