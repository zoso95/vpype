"""
Hidden debug commands to help testing.
"""
import json
from typing import Union, Any, Dict, Iterable, Sequence

import numpy as np

from .decorators import global_processor
from .model import VectorData, as_vector, LineCollection
from .vpype import cli

debug_data = []


@cli.command(hidden=True)
@global_processor
def dbsample(vector_data: VectorData):
    """
    Show statistics on the current geometries in JSON format.
    """
    global debug_data

    data = {}
    if vector_data.is_empty():
        data["count"] = 0
    else:
        data["count"] = sum(len(lc) for lc in vector_data.layers.values())
        data["layer_count"] = len(vector_data.layers)
        data["length"] = vector_data.length()
        data["bounds"] = vector_data.bounds()
        data["layers"] = {
            layer_id: [as_vector(line).tolist() for line in layer]
            for layer_id, layer in vector_data.layers.items()
        }

    debug_data.append(data)
    return vector_data


@cli.command(hidden=True)
@global_processor
def dbdump(vector_data: VectorData):
    global debug_data
    print(json.dumps(debug_data))
    debug_data = []
    return vector_data


class DebugData:
    """
    Helper class to load
    """

    @staticmethod
    def load(debug_output: str):
        """
        Create DebugData instance array from debug output
        :param debug_output:
        :return:
        """
        return [DebugData(data) for data in json.loads(debug_output)]

    def __init__(self, data: Dict[str, Any]):
        self.count = data["count"]
        self.length = data.get("length", 0)
        self.bounds = data.get("bounds", [0, 0, 0, 0])
        self.layers = data.get("layers", {})

        self.vector_data = VectorData()
        for vid, lines in self.layers.items():
            self.vector_data[int(vid)] = LineCollection(
                [np.array([x + 1j * y for x, y in line]) for line in lines]
            )

    def bounds_within(
        self, x: float, y: float, width: Union[float, None], height: Union[float, None],
    ) -> bool:
        """
        Test if coordinates are inside. If `x` and `y` are provided only, consider input as
        a point. If `width` and `height` are passed as well, consider input as rect.
        """
        if self.count == 0:
            return False

        if (
            self.bounds[0] < x
            or self.bounds[1] < y
            or self.bounds[2] > x + width
            or self.bounds[3] > y + height
        ):
            return False

        return True

    def __eq__(self, other: "DebugData"):
        if self.count == 0:
            return other.count == 0

        return (
            np.all(np.isclose(np.array(self.bounds), np.array(other.bounds)))
            and self.length == other.length
        )

    def has_layer(self, lid: int) -> bool:
        return self.has_layers([lid])

    def has_layers(self, lids: Iterable[int]) -> bool:
        return all(str(lid) in self.layers for lid in lids)

    def has_layer_only(self, lid: int) -> bool:
        return self.has_layers_only([lid])

    def has_layers_only(self, lids: Sequence[int]) -> bool:
        return self.has_layers(lids) and len(self.layers.keys()) == len(lids)


@cli.command(hidden=True)
@global_processor
def stat(vector_data: VectorData):
    """
    Print human-readable statistics on the current geometries.
    """
    global debug_data

    print("========= Stats ========= ")
    print(f"Layer count: {len(vector_data.layers)}")
    for layer_id in sorted(vector_data.layers.keys()):
        layer = vector_data.layers[layer_id]
        print(f"Layer {layer_id}")
        print(f"  Length: {layer.length()}")
        print(f"  Count: {len(layer)}")
        print(f"  Bounds: {layer.bounds()}")
    print(f"Totals")
    print(f"  Length: {vector_data.length()}")
    print(f"  Count: {sum(len(layer) for layer in vector_data.layers.values())}")
    print(f"  Bounds: {vector_data.bounds()}")
    print("========================= ")

    return vector_data
