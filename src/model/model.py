from __future__ import annotations

import math
from collections import deque

from mesa import Agent, Model
from mesa.space import PropertyLayer, SingleGrid

from model.entities.boat import (
    BOAT_FOOTPRINTS,
    Boat,
    DIRECTION_EAST,
    DIRECTION_NORTH,
    DIRECTION_SOUTH,
    DIRECTION_WEST,
)
from model.map_io import fuse_tiles, load_map, load_port_config
from model.pathfinding import generate_flow_field
from model.scenario import Scenario
from model.tiles.deposit_zone import DepositZone


class World(Model):
    """Port simulation.

    Terrain values: ``0`` water, ``1`` earth, ``2`` deposit station,
    ``3`` fuel station, ``4`` entry/exit, ``5`` artificial land,
    ``8`` water next to a deposit and ``18`` water next to a fuel station.
    """

    fuel_threshold = 25.0
    FISH_UNLOAD_PER_STEP = 2
    deposit_access_position = (6, 11)

    WATER = 0
    TERRAIN = 1
    FUEL_STATION = 3
    DEPOSIT_STATION = 2
    ENTRY_EXIT = 4
    FUEL_ADJACENT = 18
    DEPOSIT_ADJACENT = 8

    NAVIGABLE = frozenset({WATER, ENTRY_EXIT, FUEL_ADJACENT, DEPOSIT_ADJACENT})
    STEPS_PER_HOUR = 300
    SIMULATION_HOURS = 24
    MAX_STEPS = STEPS_PER_HOUR * SIMULATION_HOURS
    REVENUE_INTERVAL_MINUTES = 30
    STEPS_PER_REVENUE_INTERVAL = STEPS_PER_HOUR * REVENUE_INTERVAL_MINUTES // 60

    def __init__(
        self,
        scenario: Scenario = Scenario(),
        demo_boat_fish: int | None = None,
    ):
        if scenario.scale < 1 or isinstance(scenario.scale, bool):
            raise ValueError("scenario.scale must be a positive integer")
        if scenario.fish_price < 0 or scenario.fuel_price < 0:
            raise ValueError("fish_price and fuel_price must be non-negative")

        super().__init__(seed=scenario.seed)

        self.ship_spawn_rate = scenario.ship_spawn_rate
        self.fish_amount = scenario.fish_amount
        self.fish_standard_deviation = scenario.fish_standard_deviation
        self.boat_scale = scenario.boat_scale
        self.fish_price = scenario.fish_price
        self.fuel_price = scenario.fuel_price
        self.fuel_station_construction_cost = (
            scenario.fuel_station_construction_cost
        )
        self.deposit_station_construction_cost = (
            scenario.deposit_station_construction_cost
        )
        self.map_name = scenario.map_name
        self.port_config_name = scenario.port_config_name

        if scenario.area_tiles is not None and scenario.port_tiles is not None:
            area_tiles = scenario.area_tiles
            port_tiles = scenario.port_tiles
        else:
            area_tiles = load_map(scenario.map_name)["tiles"]
            port_tiles = load_port_config(
                scenario.map_name, scenario.port_config_name
            )["tiles"]
        fused_tiles = fuse_tiles(area_tiles, port_tiles)

        self.fuel_station_count = self._count_station_components(
            fused_tiles, self.FUEL_STATION
        )
        self.deposit_station_count = self._count_station_components(
            fused_tiles, self.DEPOSIT_STATION
        )
        self.total_construction_cost = (
            self.fuel_station_count * self.fuel_station_construction_cost
            + self.deposit_station_count
            * self.deposit_station_construction_cost
        )

        self.boats: list[Boat] = []
        self.score = 0.0
        self.total_fish_deposited = 0
        self.total_reimbursed_price = 0.0
        self.total_fuel_refilled = 0.0
        self.total_fuel_paid = 0.0
        self.total_boats_serviced = 0
        self.boats_spawned = 0
        self.revenue_per_interval: list[float] = []
        self.current_interval_revenue = 0.0
        self._last_total_revenue = 0.0
        self.flow_fields: dict = {}

        tiles = self._build_scaled_tiles(fused_tiles, scenario.scale)
        height = len(tiles)
        width = len(tiles[0])
        self.grid = SingleGrid(width, height, scenario.torus)
        self.grid.add_property_layer(
            PropertyLayer("terrain", width, height, default_value=0, dtype=int)
        )

        terrain_layer = self.grid.properties["terrain"]
        for row_idx, row in enumerate(tiles):
            y = height - 1 - row_idx
            for x, value in enumerate(row):
                terrain_layer.set_cell((x, y), value)

        self.map_data = {
            "width": width,
            "height": height,
            "scale": scenario.scale,
            "tiles": tiles,
        }

        self.entry_exit_cells = [
            (x, y)
            for x in range(width)
            for y in range(height)
            if terrain_layer.data[x][y] == self.ENTRY_EXIT
        ]
        if not self.entry_exit_cells:
            raise ValueError(
                "The map has no entry/exit cell "
                f"(value {self.ENTRY_EXIT}). Check the map and its port "
                "configuration."
            )
        self.boat_spawn_position = self.entry_exit_cells[0]
        self.deposit_stations = self._find_deposit_stations()

        self.agitation = self.compute_agitation()
        agitation_layer = PropertyLayer(
            "agitation", width, height, default_value=0.0, dtype=float
        )
        self.grid.add_property_layer(agitation_layer)
        for x in range(width):
            for y in range(height):
                # NaN keeps land and stations transparent instead of coloured.
                value = (
                    self.agitation[x][y]
                    if terrain_layer.data[x][y] in self.NAVIGABLE
                    else float("nan")
                )
                agitation_layer.set_cell((x, y), value)

        self.update_deposit_flow_field()

        if demo_boat_fish is not None:
            demo_boat = Boat(
                size=3,
                name="Demo boat",
                speed=1,
                capacity=max(50, demo_boat_fish),
                fuel_consumption=1,
                fish=demo_boat_fish,
            )
            self.add_boat(demo_boat, self.boat_spawn_position)

    @staticmethod
    def _count_station_components(
        tiles: tuple[tuple[int, ...], ...], station_value: int
    ) -> int:
        """Count connected groups of station cells."""
        station_cells = {
            (x, y)
            for y, row in enumerate(tiles)
            for x, value in enumerate(row)
            if value == station_value
        }
        count = 0
        while station_cells:
            count += 1
            pending = [station_cells.pop()]
            while pending:
                x, y = pending.pop()
                for neighbor in (
                    (x - 1, y),
                    (x + 1, y),
                    (x, y - 1),
                    (x, y + 1),
                ):
                    if neighbor in station_cells:
                        station_cells.remove(neighbor)
                        pending.append(neighbor)
        return count

    def _build_scaled_tiles(self, source_tiles, map_scale: int):
        source_height = len(source_tiles)
        source_width = len(source_tiles[0])
        if source_height == 0 or any(
            len(row) != source_width for row in source_tiles
        ):
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
                if value != self.WATER:
                    continue
                neighbors = [
                    expanded_tiles[ny][nx]
                    for nx, ny in (
                        (x - 1, y),
                        (x + 1, y),
                        (x, y - 1),
                        (x, y + 1),
                    )
                    if 0 <= nx < width
                    and 0 <= ny < height
                    and expanded_tiles[ny][nx]
                    in (self.DEPOSIT_STATION, self.FUEL_STATION)
                ]
                if neighbors:
                    row[x] = (
                        self.DEPOSIT_ADJACENT
                        if neighbors[0] == self.DEPOSIT_STATION
                        else self.FUEL_ADJACENT
                    )

        return expanded_tiles

    def compute_agitation(self) -> list[list[float]]:
        """Return water roughness, from ``0.0`` calm to ``1.0`` rough.

        For each water cell, follow the first step of the shortest path to
        every open-water cell. In a sheltered basin all paths leave through the
        same channel, so their directions barely differ and the water is calm.
        In open water paths to opposite exits point in opposite directions and
        the water is rough. The result is indexed as ``agitation[x][y]``.
        """
        width = self.grid.width
        height = self.grid.height
        terrain = self.grid.properties["terrain"].data

        steps = [
            (1, 0),
            (1, 1),
            (0, 1),
            (-1, 1),
            (-1, 0),
            (-1, -1),
            (0, -1),
            (1, -1),
        ]
        angles = [math.atan2(dy, dx) for dx, dy in steps]
        angle_diff = [
            [
                min(
                    abs(angles[i] - angles[j]),
                    2 * math.pi - abs(angles[i] - angles[j]),
                )
                for j in range(8)
            ]
            for i in range(8)
        ]

        def is_navigable(x: int, y: int) -> bool:
            return (
                0 <= x < width
                and 0 <= y < height
                and terrain[x][y] in self.NAVIGABLE
            )

        cells: list[tuple[int, int]] = []
        index: dict[tuple[int, int], int] = {}
        for y in range(height):
            for x in range(width):
                if is_navigable(x, y):
                    index[(x, y)] = len(cells)
                    cells.append((x, y))
        count = len(cells)
        if count == 0:
            return [[0.0] * height for _ in range(width)]

        neighbours: list[list[tuple[int, int]]] = [[] for _ in range(count)]
        for i, (x, y) in enumerate(cells):
            for direction, (dx, dy) in enumerate(steps):
                j = index.get((x + dx, y + dy))
                if j is not None:
                    neighbours[i].append((j, direction))

        open_ids = [
            index[(x, y)]
            for x in range(width)
            for y in range(height)
            if terrain[x][y] == self.ENTRY_EXIT
        ]
        if not open_ids:
            open_ids = [
                index[(x, y)]
                for (x, y) in cells
                if x in (0, width - 1) or y in (0, height - 1)
            ]

        # Neighbouring exits yield nearly identical directions, so sampling a
        # regular subset keeps start-up fast without changing the result much.
        stride = max(1, len(open_ids) // 150)
        open_ids = open_ids[::stride]

        out_dirs = [0] * count
        distance = [-1] * count

        for source in open_ids:
            for i in range(count):
                distance[i] = -1
            distance[source] = 0
            queue: deque[int] = deque([source])
            while queue:
                current = queue.popleft()
                next_distance = distance[current] + 1
                for neighbour, _ in neighbours[current]:
                    if distance[neighbour] < 0:
                        distance[neighbour] = next_distance
                        queue.append(neighbour)

            for i in range(count):
                dist = distance[i]
                if dist <= 0:
                    continue
                for neighbour, direction in neighbours[i]:
                    if distance[neighbour] == dist - 1:
                        out_dirs[i] |= 1 << direction
                        break

        agitation = [[0.0] * height for _ in range(width)]
        for i, (x, y) in enumerate(cells):
            if terrain[x][y] == self.ENTRY_EXIT:
                agitation[x][y] = 1.0
                continue

            directions = [d for d in range(8) if out_dirs[i] >> d & 1]
            if len(directions) < 2:
                agitation[x][y] = 0.0
                continue

            widest = 0.0
            for a in range(len(directions)):
                for b in range(a + 1, len(directions)):
                    diff = angle_diff[directions[a]][directions[b]]
                    if diff > widest:
                        widest = diff
            agitation[x][y] = widest / math.pi

        return agitation

    def is_cell_walkable(self, x: int, y: int) -> bool:
        """Return whether ``(x, y)`` is navigable water."""
        if self.grid.out_of_bounds((x, y)):
            return False
        terrain = self.grid.properties["terrain"].data[x][y]
        return terrain in self.NAVIGABLE

    def get_available_deposit_positions(self) -> list[tuple[int, int]]:
        """Service cells of free stations, or of every station if all are busy."""
        available = [
            position
            for station in self.deposit_stations
            if not station.is_occupied
            for position in station.access_positions
            if self.grid.is_cell_empty(position)
        ]
        if available:
            return available
        return [
            position
            for station in self.deposit_stations
            for position in station.access_positions
        ]

    def _find_deposit_stations(self) -> list[DepositZone]:
        """Build one station per connected group of deposit cells."""
        terrain = self.grid.properties["terrain"].data
        remaining = {
            (x, y)
            for x in range(self.grid.width)
            for y in range(self.grid.height)
            if terrain[x][y] == self.DEPOSIT_STATION
        }
        stations = []
        while remaining:
            first = remaining.pop()
            cells = {first}
            pending = deque([first])
            while pending:
                x, y = pending.popleft()
                for neighbor in (
                    (x - 1, y),
                    (x + 1, y),
                    (x, y - 1),
                    (x, y + 1),
                ):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        cells.add(neighbor)
                        pending.append(neighbor)

            access_positions = {
                neighbor
                for x, y in cells
                for neighbor in (
                    (x - 1, y),
                    (x + 1, y),
                    (x, y - 1),
                    (x, y + 1),
                )
                if not self.grid.out_of_bounds(neighbor)
                and terrain[neighbor[0]][neighbor[1]] == self.DEPOSIT_ADJACENT
            }
            if access_positions:
                stations.append(
                    DepositZone(
                        self,
                        cells=tuple(sorted(cells)),
                        access_positions=tuple(sorted(access_positions)),
                    )
                )
        return stations

    def _set_boat_target(
        self,
        boat: Boat,
        target: tuple[int, int],
        *,
        targets: list[tuple[int, int]] | None = None,
    ) -> None:
        field_key = ("boat", id(boat))
        boat.navigation_target = target
        boat.navigation_path = []
        boat.flow_field_key = field_key
        if targets is None:
            self.flow_fields.pop(field_key, None)
            return
        self.flow_fields[field_key] = generate_flow_field(
            self.grid,
            targets=targets,
            is_walkable_func=self.is_cell_walkable,
        )

    def _find_station_target(
        self,
        boat: Boat,
        station: DepositZone,
    ) -> tuple[
        tuple[int, int],
        int,
        list[tuple[tuple[int, int], int]],
    ] | None:
        if boat.position is None:
            return None

        directions = (
            DIRECTION_NORTH,
            DIRECTION_EAST,
            DIRECTION_SOUTH,
            DIRECTION_WEST,
        )
        targets = set(station.access_positions)
        start = boat.position
        parents: dict[
            tuple[int, int],
            tuple[tuple[int, int], int] | None,
        ] = {start: None}
        pending = deque([start])
        target_paths: dict[
            tuple[tuple[int, int], int],
            list[tuple[tuple[int, int], int]],
        ] = {}

        def path_to(
            position: tuple[int, int],
        ) -> list[tuple[tuple[int, int], int]]:
            path = []
            current = position
            while current != start:
                parent = parents[current]
                if parent is None:
                    break
                previous, direction = parent
                path.append((current, direction))
                current = previous
            path.reverse()
            return path

        if start in targets:
            for direction in directions:
                if self._boat_fits_at(boat, start, direction):
                    target_paths[(start, direction)] = []

        while pending:
            current = pending.popleft()
            for dx, dy in (
                (-1, 0),
                (1, 0),
                (0, -1),
                (0, 1),
                (-1, -1),
                (-1, 1),
                (1, -1),
                (1, 1),
            ):
                neighbor = (current[0] + dx, current[1] + dy)
                direction = Boat._direction_from_delta(dx, dy)

                if neighbor in targets:
                    path_prefix = path_to(current)
                    for target_direction in directions:
                        key = (neighbor, target_direction)
                        if (
                            key not in target_paths
                            and self._boat_fits_at(
                                boat, neighbor, target_direction
                            )
                        ):
                            target_paths[key] = path_prefix + [
                                (neighbor, target_direction)
                            ]

                if neighbor not in parents and self._boat_fits_at(
                    boat, neighbor, direction
                ):
                    parents[neighbor] = (current, direction)
                    pending.append(neighbor)

        if not target_paths:
            return None

        (target, direction), path = min(
            target_paths.items(),
            key=lambda item: (
                len(item[1]),
                item[0][0],
                item[0][1],
            ),
        )
        return target, direction, path

    def _assign_deposit_station(self, boat: Boat) -> None:
        if boat.position is None or boat.fish <= 0:
            return

        candidates = []
        for station in self.deposit_stations:
            target_info = self._find_station_target(boat, station)
            if target_info is None:
                continue
            target, direction, path = target_info
            candidates.append((station, len(path), target, direction, path))

        if not candidates:
            return

        station, _, target, direction, path = min(
            candidates,
            key=lambda item: (len(item[0].queue), item[1]),
        )

        station.queue.append(boat)
        boat.deposit_station = station
        boat.deposit_status = (
            "approaching" if station.active_boat is None else "waiting"
        )
        boat.navigation_direction = direction
        self._set_boat_target(boat, target)
        boat.navigation_path = path
        if station.active_boat is None:
            station.occupy(boat)

    def _boat_fits_at(
        self, boat: Boat, position: tuple[int, int], direction: int
    ) -> bool:
        previous_direction = boat.direction
        boat.direction = direction
        fits = self.can_place_boat(boat, position)
        boat.direction = previous_direction
        return fits

    def _finish_deposit(self, boat: Boat) -> None:
        station = boat.deposit_station
        if station is not None:
            was_active = station.active_boat is boat
            if boat in station.queue:
                station.queue.remove(boat)
            if was_active:
                station.release(boat)
            boat.deposit_station = None
            if station.queue:
                station.occupy(station.queue[0])
                station.queue[0].deposit_status = "approaching"

        boat.deposit_status = "exiting"
        if boat.position is not None:
            exit_directions = {}
            for position in self.entry_exit_cells:
                for direction in (
                    DIRECTION_NORTH,
                    DIRECTION_EAST,
                    DIRECTION_SOUTH,
                    DIRECTION_WEST,
                ):
                    if self._boat_fits_at(boat, position, direction):
                        exit_directions[position] = direction
                        break
            boat.exit_directions = exit_directions
            exit_targets = list(exit_directions) or self.entry_exit_cells
            nearest_exit = min(
                exit_targets,
                key=lambda position: math.dist(boat.position, position),
            )
            self._set_boat_target(
                boat,
                nearest_exit,
                targets=exit_targets,
            )

    def _remove_boat(self, boat: Boat) -> None:
        self.grid.remove_agent(boat)
        boat.remove()
        if boat in self.boats:
            self.boats.remove(boat)
        if boat.flow_field_key is not None:
            self.flow_fields.pop(boat.flow_field_key, None)

    def update_deposit_flow_field(self) -> None:
        """Rebuild the flow field toward the available deposit access cells."""
        targets = self.get_available_deposit_positions()
        if targets:
            self.flow_fields["deposit"] = generate_flow_field(
                self.grid,
                targets=targets,
                is_walkable_func=self.is_cell_walkable,
            )
        else:
            self.flow_fields["deposit"] = {}

    def _find_spawn_placement(self, boat: Boat) -> tuple[int, int] | None:
        """Return a free entry cell where the boat footprint fits."""
        placements: list[tuple[tuple[int, int], int]] = []
        for position in self.entry_exit_cells:
            for direction in (
                DIRECTION_NORTH,
                DIRECTION_EAST,
                DIRECTION_SOUTH,
                DIRECTION_WEST,
            ):
                previous_direction = boat.direction
                boat.direction = direction
                fits = self.can_boat_move_to(boat, position)
                boat.direction = previous_direction
                if fits:
                    placements.append((position, direction))

        if not placements:
            return None

        position, direction = self.random.choice(placements)
        boat.direction = direction
        return position

    def spawn_boats(self) -> list[Boat]:
        """Spawn one random boat on a free entry cell with probability
        ``ship_spawn_rate``; its fish follow a normal distribution."""
        if self.ship_spawn_rate <= 0:
            return []
        if self.random.random() >= self.ship_spawn_rate:
            return []

        size = self.random.choice(tuple(BOAT_FOOTPRINTS))
        fish = max(
            0,
            round(
                self.random.gauss(
                    self.fish_amount,
                    self.fish_standard_deviation,
                )
            ),
        )
        boat = Boat(
            size=size,
            name=f"Boat {self.boats_spawned + 1}",
            speed=1,
            capacity=max(fish, self.fish_amount, 1),
            fuel_consumption=1,
            fish=fish,
        )

        position = self._find_spawn_placement(boat)
        if position is None:
            return []

        self.add_boat(boat, position)
        self.boats_spawned += 1
        return [boat]

    def step(self):
        """Spawn boats, then move and service them."""
        self.spawn_boats()

        for boat in list(self.boats):
            if boat.position is None:
                continue

            if boat.deposit_status == "exiting":
                boat.step()
                if boat.position in self.entry_exit_cells:
                    self._remove_boat(boat)
                continue

            if boat.fish <= 0:
                self._finish_deposit(boat)
                continue

            terrain = self.grid.properties["terrain"].data
            x, y = boat.position
            if (
                boat.deposit_station is None
                and terrain[x][y] != self.ENTRY_EXIT
            ):
                self._assign_deposit_station(boat)

            boat.step()

            if boat.deposit_station is None and boat.position is not None:
                x, y = boat.position
                if terrain[x][y] != self.ENTRY_EXIT:
                    self._assign_deposit_station(boat)

            self.service_boat(boat)
            if boat.fish <= 0:
                self._finish_deposit(boat)

        self._record_revenue()
        self.steps += 1
        if self.steps >= self.MAX_STEPS:
            self.running = False

    def _record_revenue(self) -> None:
        """Close a 30-minute revenue interval when the step count reaches it."""
        current_total = self.total_revenue
        self.current_interval_revenue += (
            current_total - self._last_total_revenue
        )
        self._last_total_revenue = current_total
        if (self.steps + 1) % self.STEPS_PER_REVENUE_INTERVAL == 0:
            self.revenue_per_interval.append(self.current_interval_revenue)
            self.current_interval_revenue = 0.0

    @property
    def simulation_time(self) -> str:
        """Simulated time in 12-hour format."""
        total_minutes = self.steps * 60 // self.STEPS_PER_HOUR
        hours_24, minutes = divmod(total_minutes, 60)
        hours_12 = 0 if hours_24 == self.SIMULATION_HOURS else (
            hours_24 if hours_24 <= 12 else hours_24 - 12
        )
        period = (
            "am"
            if hours_24 < 12 or hours_24 == self.SIMULATION_HOURS
            else "pm"
        )
        return f"{hours_12}:{minutes:02d}{period}"

    @property
    def deposit_revenue(self) -> float:
        return self.total_fish_deposited * self.fish_price

    @property
    def fuel_station_revenue(self) -> float:
        return self.total_fuel_refilled * self.fuel_price

    @property
    def total_revenue(self) -> float:
        return self.deposit_revenue + self.fuel_station_revenue

    @property
    def total_cost(self) -> float:
        return self.total_construction_cost

    @property
    def fuel_station_total_cost(self) -> float:
        return self.fuel_station_count * self.fuel_station_construction_cost

    @property
    def deposit_station_total_cost(self) -> float:
        return (
            self.deposit_station_count
            * self.deposit_station_construction_cost
        )

    @property
    def fuel_station_profit(self) -> float:
        return self.fuel_station_revenue - self.fuel_station_total_cost

    @property
    def deposit_station_profit(self) -> float:
        return self.deposit_revenue - self.deposit_station_total_cost

    @property
    def profit(self) -> float:
        return self.total_revenue - self.total_cost

    @property
    def elapsed_hours(self) -> float:
        return self.steps / self.STEPS_PER_HOUR

    @property
    def revenue_per_hour(self) -> float:
        if self.elapsed_hours <= 0:
            return 0.0
        return self.total_revenue / self.elapsed_hours

    @property
    def estimated_daily_revenue(self) -> float:
        return self.revenue_per_hour * 24

    @property
    def estimated_annual_revenue(self) -> float:
        return self.estimated_daily_revenue * 365

    @property
    def estimated_break_even_days(self) -> float | None:
        if self.estimated_daily_revenue <= 0:
            return None
        return self.total_cost / self.estimated_daily_revenue

    @property
    def estimated_break_even_years(self) -> float | None:
        days = self.estimated_break_even_days
        return None if days is None else days / 365

    @property
    def estimated_days_remaining(self) -> float | None:
        if self.estimated_daily_revenue <= 0:
            return None
        remaining = max(0.0, self.total_cost - self.total_revenue)
        return remaining / self.estimated_daily_revenue

    @property
    def estimated_annual_roi(self) -> float | None:
        if self.total_cost <= 0 or self.elapsed_hours <= 0:
            return None
        return self.estimated_annual_revenue / self.total_cost

    def service_boat(self, boat: Boat) -> bool:
        """Unload fish and refill fuel when the boat touches a service zone."""
        if boat.position is None:
            return False

        x, y = boat.position
        agitation = self.agitation[x][y]
        efficiency = max(0.2, 1.0 - agitation * 0.8)

        serviced = False
        zones = self.zones_at_position(boat.position)

        station = boat.deposit_station
        # Waiting boats also drive to a berth, so any boat that reached its
        # assigned cell may unload. Refusing them would park them there and
        # block the active boat forever.
        is_at_assigned_station = (
            station is not None
            and boat.position == boat.navigation_target
        )
        if "deposit" in zones and boat.fish > 0 and is_at_assigned_station:
            if self.random.random() < efficiency:
                unloaded = min(boat.fish, self.FISH_UNLOAD_PER_STEP)
                boat.fish -= unloaded
                self.total_fish_deposited += unloaded
                revenue = unloaded * self.fish_price
                self.total_reimbursed_price += revenue
                self.score += revenue
                serviced = True

        if "fuel" in zones and boat.fuel < self.fuel_threshold:
            if self.random.random() < efficiency:
                refilled = boat.fuel_capacity - boat.fuel
                boat.fuel = boat.fuel_capacity
                self.total_fuel_refilled += refilled
                self.total_fuel_paid += refilled * self.fuel_price
                self.score -= refilled * self.fuel_price
                serviced = True

        if serviced:
            self.total_boats_serviced += 1
        return serviced

    def can_place_boat(
        self,
        boat: Boat,
        position: tuple[int, int],
        *,
        allow_access: bool = False,
    ) -> bool:
        """Return whether the whole boat footprint fits on navigable cells."""
        terrain_layer = self.grid.properties["terrain"].data
        for cell_x, cell_y in boat.occupied_cells(position):
            if not (
                0 <= cell_x < self.grid.width
                and 0 <= cell_y < self.grid.height
            ):
                return False
            if terrain_layer[cell_x][cell_y] in self.NAVIGABLE:
                continue
            if allow_access and (cell_x, cell_y) == self.deposit_access_position:
                continue
            return False
        return True

    def can_boat_move_to(
        self,
        boat: Boat,
        position: tuple[int, int],
        *,
        allow_access: bool = False,
    ) -> bool:
        """Check both the terrain and the footprints of other boats."""
        if not self.can_place_boat(boat, position, allow_access=allow_access):
            return False

        target_cells = set(boat.occupied_cells(position))
        for other in self.boats:
            if other is boat or other.position is None:
                continue
            if target_cells.intersection(other.occupied_cells()):
                return False
        return True

    def move_boat(
        self,
        boat: Boat,
        dx: int,
        dy: int,
        direction: int | None = None,
    ) -> bool:
        """Move the boat if its whole footprint fits; rotation is atomic."""
        position = boat.position
        if position is None:
            return False

        previous_direction = boat.direction
        if direction is not None:
            boat.direction = int(direction) % 4

        target = (position[0] + dx, position[1] + dy)
        if not self.can_boat_move_to(boat, target):
            boat.direction = previous_direction
            return False

        self.grid.move_agent(boat, target)
        return True

    def add_boat(self, boat: Boat, position: tuple[int, int]) -> Boat:
        """Place a boat on a free navigable cell."""
        if not isinstance(boat, Boat):
            raise TypeError("boat must be a Boat")
        if not self.can_place_boat(
            boat, position, allow_access=True
        ) or not self.can_boat_move_to(boat, position, allow_access=True):
            raise ValueError(
                "boats must be placed on unoccupied navigable cells "
                "(all footprint cells)"
            )

        if getattr(boat, "model", None) is None:
            Agent.__init__(boat, self)
        self.grid.place_agent(boat, position)
        if boat not in self.boats:
            self.boats.append(boat)
        return boat

    def zones_at_position(self, position: tuple[int, int]) -> set[str]:
        """Service zones occupied by or adjacent to ``position``."""
        x, y = position
        positions = [(x, y)]
        positions.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))

        zones: set[str] = set()
        terrain_data = self.grid.properties["terrain"].data
        for nx, ny in positions:
            if self.grid.out_of_bounds((nx, ny)):
                continue
            terrain = terrain_data[nx][ny]
            if terrain in (self.FUEL_STATION, self.FUEL_ADJACENT):
                zones.add("fuel")
            elif terrain in (self.DEPOSIT_STATION, self.DEPOSIT_ADJACENT):
                zones.add("deposit")
        return zones
