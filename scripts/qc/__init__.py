"""Vocello QC v2: a lean audio QC harness calibrated on human recordings and the maintainer's ears.

`scripts/qc.py` is the command line. The modules here hold the model registry
(`models`), the runner host (`runtime`), paths and caches (`store`), the label
tool (`label`), the calibration on human controls (`calibrate`), the chat
confirmations (`confirm`), and the per-take features, detectors, fits and lanes. Model
runners live under `qc.runners` and run in their own pinned venvs. See
docs/reference/qc.md.
"""
