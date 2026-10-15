from tempfile import TemporaryDirectory
import unittest

import numpy as np

from har.inference import predict_windows
from har.live_predict import SMOOTHING_WINDOWS, UNCERTAIN_BELOW, LivePredictor
from har.tests.fixtures import grouped_fixture
from har.tests.test_inference import build_run


class StubEstimator:
    def __init__(self, rows):
        self.classes_ = np.array(["lie", "sit", "stand", "walk"])
        self._rows = iter(rows)

    def predict_proba(self, features):
        return np.array([next(self._rows)])


class LivePredictorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = TemporaryDirectory()
        cls.run_dir = build_run(cls._tmp.name)
        cls.windows = grouped_fixture([31]).windows

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_raw_probabilities_match_batch_prediction(self):
        predictor = LivePredictor(self.run_dir)
        batch = predict_windows(self.run_dir, self.windows)
        for window, expected in zip(self.windows, batch["probabilities"]):
            predictor.reset()
            result = predictor.predict(window)
            np.testing.assert_allclose(result["raw_probabilities"], expected, rtol=0, atol=1e-12)
            self.assertEqual(result["raw_label"],
                             predictor.labels[int(np.argmax(result["raw_probabilities"]))])
            self.assertEqual(result["raw_probabilities"], result["probabilities"])
            self.assertGreaterEqual(result["predict_ms"], 0.0)
        random_windows = np.random.default_rng(0).normal(size=(5, 128, 6))
        random_batch = predict_windows(self.run_dir, random_windows)
        for window, expected in zip(random_windows, random_batch["probabilities"]):
            predictor.reset()
            np.testing.assert_allclose(predictor.predict(window)["raw_probabilities"], expected,
                                       rtol=0, atol=1e-12)
        self.assertEqual(predictor.labels, batch["labels"])

    def test_smoothing_averages_last_three_windows(self):
        predictor = LivePredictor(self.run_dir)
        raws = [predictor.predict(w)["raw_probabilities"] for w in self.windows[:3]]
        result = predictor.predict(self.windows[3])
        raws.append(result["raw_probabilities"])
        self.assertEqual(SMOOTHING_WINDOWS, 3)
        np.testing.assert_allclose(result["probabilities"], np.mean(raws[-3:], axis=0))
        best = int(np.argmax(result["probabilities"]))
        self.assertEqual(result["label"], predictor.labels[best])

    def test_reset_forgets_previous_windows(self):
        predictor = LivePredictor(self.run_dir)
        predictor.predict(self.windows[0])
        predictor.reset()
        result = predictor.predict(self.windows[6])
        self.assertEqual(result["probabilities"], result["raw_probabilities"])

    def test_uncertain_below_threshold(self):
        predictor = LivePredictor(self.run_dir)
        predictor._estimator = StubEstimator([[0.5, 0.3, 0.1, 0.1], [0.7, 0.1, 0.1, 0.1],
                                           [0.9, 0.1, 0.0, 0.0], [0.1, 0.9, 0.0, 0.0],
                                           [0.6, 0.4, 0.0, 0.0]])
        predictor.labels = ["lie", "sit", "stand", "walk"]
        self.assertEqual(UNCERTAIN_BELOW, 0.60)
        first = predictor.predict(self.windows[0])
        self.assertTrue(first["uncertain"])
        self.assertEqual(first["label"], "lie")
        predictor.reset()
        self.assertFalse(predictor.predict(self.windows[0])["uncertain"])
        predictor.reset()
        predictor.predict(self.windows[0])
        second = predictor.predict(self.windows[0])
        self.assertTrue(second["uncertain"])
        self.assertAlmostEqual(max(second["probabilities"]), 0.5)
        self.assertAlmostEqual(max(second["raw_probabilities"]), 0.9)
        predictor.reset()
        exact = predictor.predict(self.windows[0])
        self.assertEqual(max(exact["probabilities"]), UNCERTAIN_BELOW)
        self.assertFalse(exact["uncertain"])

    def test_rejects_wrong_shape(self):
        with self.assertRaises(ValueError):
            LivePredictor(self.run_dir).predict(np.zeros((64, 6)))


