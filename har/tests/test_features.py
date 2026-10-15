import unittest

import numpy as np

from har.features import extract_features, feature_names


class FeatureTests(unittest.TestCase):
    def test_gravity_and_constant_channels(self):
        w = np.zeros((2, 128, 6))
        w[:, :, 2] = 1
        f = extract_features(w)
        names = feature_names()
        self.assertEqual(f.shape, (2, 70))
        self.assertEqual(len(set(names)), 70)
        np.testing.assert_allclose(f[:, names.index("az_mean")], 1)
        np.testing.assert_allclose(f[:, names.index("acc_mag_rms")], 1)
        np.testing.assert_allclose(f[:, names.index("corr_ax_ay")], 0)
        self.assertTrue(np.isfinite(f).all())

    def test_signed_ramp_has_hand_derived_statistics(self):
        w = np.zeros((1, 128, 6))
        w[0, :, 0] = np.tile([-1., 1.], 64)
        w[0, :, 1] = -w[0, :, 0]
        f = extract_features(w)[0]
        names = feature_names()
        for stat, expected in (("mean", 0), ("std", 1), ("min", -1),
                               ("max", 1), ("rms", 1), ("iqr", 2)):
            self.assertAlmostEqual(f[names.index("ax_" + stat)], expected)
        self.assertAlmostEqual(f[names.index("corr_ax_ay")], -1)

    def test_batch_matches_individual_windows(self):
        w = np.random.default_rng(12).normal(size=(3, 128, 6))
        np.testing.assert_allclose(extract_features(w),
                                   np.vstack([extract_features(x[None]) for x in w]))

    def test_empty_has_schema(self):
        self.assertEqual(extract_features(np.empty((0, 128, 6))).shape, (0, 70))

    def test_invalid_shape_rejected(self):
        for shape in ((128, 6), (1, 127, 6), (1, 128, 5)):
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                extract_features(np.zeros(shape))

    def test_nonfinite_rejected(self):
        for bad in (np.nan, np.inf, -np.inf):
            w = np.zeros((1, 128, 6))
            w[0, 3, 0] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                extract_features(w)
