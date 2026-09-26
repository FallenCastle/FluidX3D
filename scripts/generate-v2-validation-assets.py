#!/usr/bin/env python3
"""Generate deterministic binary STL assets used by V2 validation cases."""
from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = ROOT / "configs" / "assets"


def triangle(a, b, c):
    return struct.pack("<12fH", 0.0, 0.0, 0.0, *a, *b, *c, 0)


faces = [
    (0, 2, 1), (0, 3, 2),
    (4, 5, 6), (4, 6, 7),
    (0, 1, 5), (0, 5, 4),
    (1, 2, 6), (1, 6, 5),
    (2, 3, 7), (2, 7, 6),
    (3, 0, 4), (3, 4, 7),
]


def write_box(filename, dimensions):
    x, y, z = dimensions
    vertices = [
        (0.0, 0.0, 0.0), (x, 0.0, 0.0), (x, y, 0.0), (0.0, y, 0.0),
        (0.0, 0.0, z), (x, 0.0, z), (x, y, z), (0.0, y, z),
    ]
    label = ("Solver-IBM deterministic V2 unit cube" if dimensions == (1.0, 1.0, 1.0)
             else f"Solver-IBM deterministic V2 box {x:g}x{y:g}x{z:g}")
    header = label.encode().ljust(80, b"\0")
    payload = header + struct.pack("<I", len(faces)) + b"".join(
        triangle(vertices[a], vertices[b], vertices[c]) for a, b, c in faces
    )
    path = OUTPUT_DIRECTORY / filename
    path.write_bytes(payload)
    print(f"{path} {len(payload)} bytes")


OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
write_box("unit-cube-binary.stl", (1.0, 1.0, 1.0))
write_box("rectangular-box-2x1x1-binary.stl", (2.0, 1.0, 1.0))
write_box("thermal-slab-1x4x4-binary.stl", (1.0, 4.0, 4.0))
