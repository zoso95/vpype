import logging
import math
from typing import Optional, Tuple

import click
import numpy as np
import rtree
from shapely.geometry import Polygon, LineString

from .decorators import layer_processor
from .model import LineCollection, as_vector
from .utils import Length
from .vpype import cli


class LineIndex:
    """Wrapper to rtree to facilitate systematic processing of a LineCollection. This
    class has many avenue for optimisation, which shan't be done until profiling says so.

    Implementation note: we use the `available` bool array because deleting stuff from the
    index is very costly.
    """

    def __init__(self, lines: LineCollection, reverse: bool = False):
        self.lines = lines
        self.reverse = reverse
        self.available = np.ones(shape=len(lines), dtype=bool)

        # create rtree index
        self.index = rtree.index.Index()
        for i, line in enumerate(lines):
            self.index.insert(i, (line[0].real, line[0].imag) * 2)

        # create reverse index
        if reverse:
            self.rindex = rtree.index.Index()
            for i, line in enumerate(lines):
                self.rindex.insert(i, (line[-1].real, line[-1].imag) * 2)

    def __len__(self) -> int:
        return np.count_nonzero(self.available)

    def __getitem__(self, item):
        return self.lines[item]

    def pop_front(self) -> Optional[np.ndarray]:
        if len(self) == 0:
            return None
        idx = int(np.argmax(self.available))
        self.available[idx] = False
        return self.lines[idx]

    def pop(self, idx: int) -> Optional[np.ndarray]:
        if not self.available[idx]:
            return None
        self.available[idx] = False
        return self.lines[idx]

    def find_closest(self, p: complex, max_dist: float) -> Tuple[Optional[int], bool]:
        """Find the closest line, assuming a maximum admissible distance.
        Returns a tuple of (idx, reverse), where `idx` may be None if nothing is found.
        `reverse` indicates whether or not a line ending has been matched instead of a start.
        False is always returned if index was created with `reverse=False`.s
        """
        idx, dist = self._find_closest_in_index(p, max_dist, self.index)
        if self.reverse:
            ridx, rdist = self._find_closest_in_index(p, max_dist, self.rindex)

            if idx is None and ridx is None:
                return None, False
            elif idx is not None and ridx is None:
                return idx, False
            elif idx is None and ridx is not None:
                return ridx, True
            elif rdist < dist:
                return ridx, True
            else:
                return idx, False
        else:
            return idx, False

    def _find_closest_in_index(
        self, p: complex, max_dist: float, index: rtree.index.Index
    ) -> Tuple[Optional[int], Optional[float]]:
        """Find nearest in specific index. Return (idx, dist) tuple, both of which can be None.
        """

        # query the index while discarding anything that is no longer available
        items = [
            item
            for item in index.intersection(
                [p.real - max_dist, p.imag - max_dist, p.real + max_dist, p.imag + max_dist],
                objects=True,
            )
            if self.available[item.id]
        ]
        if len(items) == 0:
            return None, 0

        # we want the closest item, and we want it only if it's not too far
        def item_distance(it):
            return math.hypot(p.real - it.bbox[0], p.imag - it.bbox[1])

        item = min(items, key=item_distance)
        dist = item_distance(item)
        if dist > max_dist:
            return None, 0

        return item.id, dist


@cli.command(group="Operations")
@click.argument("x", type=Length(), required=True)
@click.argument("y", type=Length(), required=True)
@click.argument("width", type=Length(), required=True)
@click.argument("height", type=Length(), required=True)
@layer_processor
def crop(lines: LineCollection, x: float, y: float, width: float, height: float):
    """
    Crop the geometries.

    The crop area is defined by the (X, Y) top-left corner and the WIDTH and HEIGHT arguments.
    All arguments understand supported units.
    """
    if lines.is_empty():
        return lines

    # Because of this bug, we cannot use shapely at MultiLineString level
    # https://github.com/Toblerity/Shapely/issues/779
    # I should probably implement it directly anyways...
    p = Polygon([(x, y), (x + width, y), (x + width, y + height), (x, y + height)])
    new_lines = LineCollection()
    for line in lines:
        res = LineString(as_vector(line)).intersection(p)
        if res.geom_type == "MultiLineString":
            new_lines.extend(res)
        elif not res.is_empty:
            new_lines.append(res)

    return new_lines


@cli.command(group="Operations")
@click.option(
    "-t",
    "--tolerance",
    type=Length(),
    default="0.05mm",
    help="Maximum distance between two line endings that should be merged.",
)
@click.option(
    "-f", "--flip", is_flag=True, help="Enables reversing stroke direction for merging."
)
@layer_processor
def linemerge(lines: LineCollection, tolerance: float, flip: bool = True):
    """
    Merge lines whose endings overlap or are very close.

    Stroke direction is preserved by default, so `linemerge` looks at joining a line's end with
    another line's start. With the `--flip` stroke direction will be reversed as required to
    further the merge.

    By default, gaps of maximum 0.05mm are considered for merging. This can be controlled with
    the `--tolerance` option.
    """
    if len(lines) < 2:
        return lines

    index = LineIndex(lines, reverse=flip)
    new_lines = LineCollection()

    while len(index) > 0:
        line = index.pop_front()

        # we append to `line` until we dont find anything to add
        while True:
            idx, reverse = index.find_closest(line[-1], tolerance)
            if idx is None and flip:
                idx, reverse = index.find_closest(line[0], tolerance)
                line = np.flip(line)
            if idx is None:
                break
            new_line = index.pop(idx)
            if reverse:
                new_line = np.flip(new_line)
            line = np.hstack([line[:-1], 0.5 * (line[-1] + new_line[0]), new_line[1:]])

        new_lines.append(line)

    logging.info(f"linemerge: reduced line count from {len(lines)} to {len(new_lines)}")
    return new_lines
