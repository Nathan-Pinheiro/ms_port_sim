import json
from pathlib import Path
import numpy as np
from mesa import Model
from mesa.space import SingleGrid, PropertyLayer


class World(Model):
    def __init__(
        self, 
        map_path=None, 
        torus=False,
        ship_spawn_rate=0.1,
        fish_amount=50,
        fish_standard_deviation=5.0,
        seed=None,
    ):
        super().__init__(seed=seed)
        
        if map_path is None:
            map_path = Path(__file__).parent.parent / "data" / "default.map.json"
        else:
            map_path = Path(map_path)

        with open(map_path, "r", encoding="utf-8") as f:
            map_data = json.load(f)

        width = map_data["width"]
        height = map_data["height"]

        self.ship_spawn_rate = ship_spawn_rate
        self.fish_amount = fish_amount
        self.fish_standard_deviation = fish_standard_deviation

        super().__init__()
        self.grid = SingleGrid(width, height, torus)

        terrain_layer = PropertyLayer(
            "terrain", width, height, default_value=0, dtype=int
        )
        self.grid.add_property_layer(terrain_layer)

        tiles = map_data["tiles"]
        for row_idx, row in enumerate(tiles):
            y = height - 1 - row_idx
            for x, value in enumerate(row):
                self.grid.properties["terrain"].set_cell((x, y), value)

        self.map_data = map_data

    def step(self):
        pass
