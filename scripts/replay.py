#!/usr/bin/env python3
"""Replay data: the file header and its metadata."""
from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path

MAGIC = b"KHERPL01"


def read_meta(path: Path) -> dict:
    with gzip.open(path, "rb") as stream:
        if stream.read(len(MAGIC)) != MAGIC:
            raise ValueError(f"{path.name} is not replay data")
        size = struct.unpack("<I", stream.read(4))[0]
        return json.loads(stream.read(size))
