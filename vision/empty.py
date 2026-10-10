"""Occupancy grid → merged empty regions."""

from __future__ import annotations

import numpy as np

from .schema import EmptyRegion, SceneObject


def empties_from_objects(
    objects: list[SceneObject],
    *,
    rows: int = 6,
    cols: int = 8,
    min_area: float = 0.04,
    max_regions: int = 8,
) -> list[EmptyRegion]:
    """Mark cells covered by object boxes; merge free 4-connected components."""
    occ = np.zeros((rows, cols), dtype=np.uint8)
    for o in objects:
        # Expand slightly so near-object cells count as occupied.
        half_w = max(o.w, o.span) * 0.55
        half_h = max(o.h, o.span * 0.75) * 0.55
        u0, u1 = o.u - half_w, o.u + half_w
        v0, v1 = o.v - half_h, o.v + half_h
        c0 = max(0, int(u0 * cols))
        c1 = min(cols - 1, int(u1 * cols))
        r0 = max(0, int(v0 * rows))
        r1 = min(rows - 1, int(v1 * rows))
        occ[r0 : r1 + 1, c0 : c1 + 1] = 1

    free = occ == 0
    visited = np.zeros_like(free, dtype=bool)
    regions: list[EmptyRegion] = []
    cell_area = 1.0 / (rows * cols)

    for r in range(rows):
        for c in range(cols):
            if not free[r, c] or visited[r, c]:
                continue
            # BFS
            stack = [(r, c)]
            visited[r, c] = True
            cells: list[tuple[int, int]] = []
            while stack:
                cr, cc = stack.pop()
                cells.append((cr, cc))
                for nr, nc in ((cr - 1, cc), (cr + 1, cc), (cr, cc - 1), (cr, cc + 1)):
                    if 0 <= nr < rows and 0 <= nc < cols and free[nr, nc] and not visited[nr, nc]:
                        visited[nr, nc] = True
                        stack.append((nr, nc))
            area = len(cells) * cell_area
            if area < min_area:
                continue
            rs = [x[0] for x in cells]
            cs = [x[1] for x in cells]
            r_min, r_max = min(rs), max(rs)
            c_min, c_max = min(cs), max(cs)
            u = (c_min + c_max + 1) / (2.0 * cols)
            v = (r_min + r_max + 1) / (2.0 * rows)
            w = (c_max - c_min + 1) / cols
            h = (r_max - r_min + 1) / rows
            regions.append(EmptyRegion(u=u, v=v, area=area, w=w, h=h))

    regions.sort(key=lambda e: e.area, reverse=True)
    return regions[:max_regions]
