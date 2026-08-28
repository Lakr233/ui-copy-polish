#!/usr/bin/env python3
"""Compatibility shim: the multi-format report lives in catalog-gaps.py."""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("catalog-gaps.py")), run_name="__main__")
