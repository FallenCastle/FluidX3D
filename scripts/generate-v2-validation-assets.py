#!/usr/bin/env python3
"""Generate deterministic binary STL assets used by V2 validation cases."""
from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "configs" / "assets" / "unit-cube-binary.stl"


def triangle(a, b, c):
    return struct.pack("<12fH", 0.0, 0.0, 0.0, *a, *b, *c, 0)


vertices = [
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (1.0, 1.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
    (1.0, 0.0, 1.0),
    (1.0, 1.0, 1.0),
    (0.0, 1.0, 1.0),
]
faces = [
    (0, 2, 1), (0, 3, 2),
    (4, 5, 6), (4, 6, 7),
    (0, 1, 5), (0, 5, 4),
    (1, 2, 6), (1, 6, 5),
    (2, 3, 7), (2, 7, 6),
    (3, 0, 4), (3, 4, 7),
]
header = b"Solver-IBM deterministic V2 unit cube".ljust(80, b"\0")
payload = header + struct.pack("<I", len(faces)) + b"".join(
    triangle(vertices[a], vertices[b], vertices[c]) for a, b, c in faces
)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_bytes(payload)
print(f"{OUTPUT} {len(payload)} bytes")
