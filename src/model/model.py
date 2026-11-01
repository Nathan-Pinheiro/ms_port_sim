from mesa import Model
from mesa.space import SingleGrid, PropertyLayer
from model.scenario import Scenario


class World(Model):
    def __init__(self, scenario: Scenario = Scenario()):
        if scenario.scale < 1 or isinstance(scenario.scale, bool):
            raise ValueError("scenario.scale must be a positive integer")
        super().__init__(seed=scenario.seed)

        self.ship_spawn_rate = scenario.ship_spawn_rate
        self.fish_amount = scenario.fish_amount
        self.fish_standard_deviation = scenario.fish_standard_deviation
        self.map_scale = scenario.scale

        tiles = self._build_scaled_tiles(scenario.tiles, scenario.scale)
        height = len(tiles)
        width = len(tiles[0])
        self.grid = SingleGrid(width, height, scenario.torus)

        terrain_layer = PropertyLayer(
            "terrain", width, height, default_value=0, dtype=int
        )
        self.grid.add_property_layer(terrain_layer)

        for row_idx, row in enumerate(tiles):
            y = height - 1 - row_idx
            for x, value in enumerate(row):
                self.grid.properties["terrain"].set_cell((x, y), value)

        self.map_data = {
            "width": scenario.width * scenario.scale,
            "height": scenario.height * scenario.scale,
            "scale": scenario.scale,
            "tiles": tiles,
        }

    @staticmethod
    def _build_scaled_tiles(source_tiles, map_scale):
        source_height = len(source_tiles)
        source_width = len(source_tiles[0])
        if source_height == 0 or any(len(row) != source_width for row in source_tiles):
            raise ValueError("The map tiles must be a non-empty rectangular grid")

        expanded_tiles = []

        for source_row in source_tiles:
            expanded_row = []
            for value in source_row:
                expanded_row.extend([value] * map_scale)
            for _ in range(map_scale):
                expanded_tiles.append(expanded_row.copy())

        height = len(expanded_tiles)
        width = len(expanded_tiles[0])
        for y, row in enumerate(expanded_tiles):
            for x, value in enumerate(row):
                if value != 0:
                    continue

                neighboring_stations = [
                    expanded_tiles[neighbor_y][neighbor_x]
                    for neighbor_x, neighbor_y in (
                        (x - 1, y),
                        (x + 1, y),
                        (x, y - 1),
                        (x, y + 1),
                    )
                    if 0 <= neighbor_x < width and 0 <= neighbor_y < height
                    and expanded_tiles[neighbor_y][neighbor_x] in (2, 3)
                ]
                if neighboring_stations:
                    station_type = neighboring_stations[0]
                    row[x] = 8 if station_type == 2 else 18

        return expanded_tiles

    def step(self):
        pass
