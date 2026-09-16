#!/usr/bin/env python3
"""Write ../golden_real_traffic.jsonl from the category modules."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import base                                                    # noqa: E402
import c_borrowing, c_finding, c_hours, c_people               # noqa: E402,F401
import c_scope, c_spaces, c_tech                               # noqa: E402,F401

base.apply_scope_library()
base.emit(pathlib.Path(__file__).resolve().parents[1] / "golden_real_traffic.jsonl")
