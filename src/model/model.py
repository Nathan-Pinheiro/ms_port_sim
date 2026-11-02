from mesa import Model
from mesa.space import SingleGrid, PropertyLayer
from model.scenario import Scenario
from model.entities.boat import Boat


class World(Model):
    fuel_threshold = 25.0
    boat_spawn_position = (0, 0)
    deposit_access_position = (6, 11)

    def __init__(self, scenario: Scenario = Scenario(), demo_boat_fish: int | None = None):
        if scenario.scale < 1 or isinstance(scenario.scale, bool):
            raise ValueError("scenario.scale must be a positive integer")
        if scenario.fish_price < 0 or scenario.fuel_price < 0:
            raise ValueError("fish_price and fuel_price must be non-negative")
        super().__init__(seed=scenario.seed)

        self.ship_spawn_rate = scenario.ship_spawn_rate
        self.fish_amount = scenario.fish_amount
        self.fish_standard_deviation = scenario.fish_standard_deviation
        self.map_scale = scenario.scale
        self.fish_price = scenario.fish_price
        self.fuel_price = scenario.fuel_price
        self.boats: list[Boat] = []
        self.score = 0.0
        self.total_fish_deposited = 0
        self.total_reimbursed_price = 0.0
        self.total_fuel_refilled = 0.0
        self.total_fuel_paid = 0.0
        self.total_boats_serviced = 0
        self.boats_teleported_to_deposit = 0

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

        if demo_boat_fish is not None:
            demo_boat = Boat(
                size=3,
                name="Demo boat",
                speed=1,
                capacity=max(50, demo_boat_fish),
                fuel_consuption=1,
                fish=demo_boat_fish,
            )
            self.add_boat(demo_boat, self.boat_spawn_position)

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
        """Teleport spawned boats to the demo deposit, then process interactions."""
        for boat in self.boats:
            if boat.position is None:
                continue

            if boat.position == self.boat_spawn_position:
                self.grid.move_agent(boat, self.deposit_access_position)
                self.boats_teleported_to_deposit += 1
                continue

            serviced = self.service_boat(boat)

        self.steps += 1

    def service_boat(self, boat: Boat) -> bool:
        """Deposit fish and refuel a boat at its current position."""
        if boat.position is None:
            return False

        serviced = False
        nearby_zones = self.zones_at_position(boat.position)
        if "deposit" in nearby_zones and boat.fish > 0:
            deposited = 1
            boat.fish -= deposited
            self.total_fish_deposited += deposited
            reimbursed_price = self.fish_price
            self.total_reimbursed_price += reimbursed_price
            self.score += reimbursed_price
            serviced = True

        if "fuel" in nearby_zones and boat.fuel < self.fuel_threshold:
            refilled = boat.fuel_capacity - boat.fuel
            boat.fuel = boat.fuel_capacity
            self.total_fuel_refilled += refilled
            self.total_fuel_paid += refilled * self.fuel_price
            self.score -= refilled * self.fuel_price
            serviced = True

        if serviced:
            self.total_boats_serviced += 1
        return serviced

    def add_boat(self, boat: Boat, position: tuple[int, int]) -> Boat:
        """Add a stationary boat to a water cell."""
        if not isinstance(boat, Boat):
            raise TypeError("boat must be a Boat")
        if not self.grid.out_of_bounds(position):
            terrain = self.grid.properties["terrain"].data[position[1]][position[0]]
            if terrain != 0 and position != self.deposit_access_position:
                raise ValueError("boats must be placed on a water cell")
        else:
            raise ValueError("boat position is outside the grid")

        if getattr(boat, "model", None) is None:
            from mesa import Agent
            Agent.__init__(boat, self)
        self.grid.place_agent(boat, position)
        if boat not in self.boats:
            self.boats.append(boat)
        return boat

    def nearby_zones(self, position: tuple[int, int]) -> set[str]:
        """Return service zones directly adjacent to a grid position."""
        return self._zones_at(position, include_position=False)

    def zones_at_position(self, position: tuple[int, int]) -> set[str]:
        """Return zones occupied by or directly adjacent to a position."""
        return self._zones_at(position, include_position=True)

    def _zones_at(
        self, position: tuple[int, int], include_position: bool
    ) -> set[str]:
        x, y = position
        zones: set[str] = set()
        positions = []
        if include_position:
            positions.append((x, y))
        positions.extend((
            (x - 1, y),
            (x + 1, y),
            (x, y - 1),
            (x, y + 1),
        ))
        for neighbor_x, neighbor_y in positions:
            if self.grid.out_of_bounds((neighbor_x, neighbor_y)):
                continue
            terrain = self.grid.properties["terrain"].data[neighbor_y][neighbor_x]
            if terrain in (2, 8):
                zones.add("fuel")
            elif terrain in (3, 18):
                zones.add("deposit")
        return zones
