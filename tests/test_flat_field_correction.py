import numpy as np

from src.flat_field_correction import correct


def test_correct_flattens_vignetting_to_mid_grey():
    dark = np.full((4, 4, 3), 10.0, dtype=np.float32)
    flat = dark + np.linspace(50, 200, 16, dtype=np.float32).reshape(4, 4, 1)
    raw = dark + (flat - dark) * 0.5

    corrected = correct(raw, flat, dark)

    assert np.allclose(corrected, 128.0, atol=1e-3)
