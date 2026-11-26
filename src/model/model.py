from __future__ import annotations

import math
from collections import deque

from mesa import Agent, Model
from mesa.space import PropertyLayer, SingleGrid

from model.entities.boat import (
    Boat,
    DEFAULT_FUEL_CAPACITY,
    DIRECTION_EAST,
    DIRECTION_NORTH,
    DIRECTION_SOUTH,
    DIRECTION_WEST,
    MOVE_ARRIVED,
    MOVE_BLOCKED,
    MOVE_MOVED,
)
from model.arrival_profiles import build_daily_arrival_schedule
from model.map_io import fuse_tiles, load_map, load_port_config
from model.pathfinding import generate_flow_field
from model.scenario import (
    DEFAULT_FISH_UNLOAD_FACTOR,
    DEFAULT_FUEL_REFILL_FACTOR,
    Scenario,
)
from model.tiles.deposit_zone import DepositZone


class World(Model):
    """Port simulation.

    Terrain values: ``0`` water, ``1`` earth, ``2`` deposit station,
    ``3`` fuel station, ``4`` entry/exit, ``5`` artificial land,
    ``8`` water next to a deposit and ``18`` water next to a fuel station.
    """

    # Fraction of fuel capacity below which an empty boat refuels.
    fuel_threshold = 0.95
    # Default fractions of capacity handled per service step; the scenario
    # values (settable in the UI) override these on each World instance.
    FISH_UNLOAD_FACTOR = DEFAULT_FISH_UNLOAD_FACTOR
    FUEL_REFILL_FACTOR = DEFAULT_FUEL_REFILL_FACTOR
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
    SIMULATION_START_HOUR = 7
    SIMULATION_END_HOUR = 21
    SIMULATION_HOURS = SIMULATION_END_HOUR - SIMULATION_START_HOUR
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
        if not (
            0 <= scenario.initial_fuel_min_ratio
            <= scenario.initial_fuel_max_ratio
            <= 1
        ):
            raise ValueError(
                "initial fuel ratios must satisfy 0 <= min <= max <= 1"
            )
        if not 0 < scenario.fish_unload_factor <= 1:
            raise ValueError("fish_unload_factor must be between 0 and 1")
        if not 0 < scenario.fuel_refill_factor <= 1:
            raise ValueError("fuel_refill_factor must be between 0 and 1")

        super().__init__(seed=scenario.seed)

        self.initial_fuel_min_ratio = scenario.initial_fuel_min_ratio
        self.initial_fuel_max_ratio = scenario.initial_fuel_max_ratio
        self.fish_unload_factor = scenario.fish_unload_factor
        self.fuel_refill_factor = scenario.fuel_refill_factor
        self.ship_spawn_rate = scenario.ship_spawn_rate
        self.port_type = scenario.port_type
        self._arrival_schedule = build_daily_arrival_schedule(
            scenario.port_type,
            self.random,
            steps_per_hour=self.STEPS_PER_HOUR,
            simulation_start_hour=self.SIMULATION_START_HOUR,
            simulation_end_hour=self.SIMULATION_END_HOUR,
        )
        self._pending_boat_sizes: deque[int] = deque()
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
        self.deposit_station_count = sum(
            1
            for row in fused_tiles
            for value in row
            if value == self.DEPOSIT_STATION
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
        # Exclusive access-cell reservations for boats heading to deposit.
        self.deposit_reservations: dict[
            tuple[int, int], Boat
        ] = {}

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
        self.deposit_access_positions = tuple(
            sorted(
                {
                    position
                    for station in self.deposit_stations
                    for position in station.access_positions
                }
            )
        )
        self.fuel_access_positions = tuple(
            (x, y)
            for x in range(width)
            for y in range(height)
            if terrain_layer.data[x][y] == self.FUEL_ADJACENT
        )

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

        self._rebuild_flow_field("deposit", self.deposit_access_positions)
        self._rebuild_flow_field("fuel", self.fuel_access_positions)

        if demo_boat_fish is not None:
            demo_boat = Boat(
                size=3,
                name="Demo boat",
                speed=1,
                capacity=max(50, demo_boat_fish),
                initial_fuel=self._random_initial_fuel(),
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

    def _find_deposit_stations(self) -> list[DepositZone]:
        """Build one station per deposit tile."""
        terrain = self.grid.properties["terrain"].data
        stations = []
        for x in range(self.grid.width):
            for y in range(self.grid.height):
                if terrain[x][y] != self.DEPOSIT_STATION:
                    continue
                access_positions = tuple(
                    sorted(
                        neighbor
                        for neighbor in (
                            (x - 1, y),
                            (x + 1, y),
                            (x, y - 1),
                            (x, y + 1),
                        )
                        if not self.grid.out_of_bounds(neighbor)
                        and terrain[neighbor[0]][neighbor[1]]
                        == self.DEPOSIT_ADJACENT
                    )
                )
                if access_positions:
                    stations.append(
                        DepositZone(
                            self,
                            cell=(x, y),
                            access_positions=access_positions,
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

    def _find_target_path(
        self,
        boat: Boat,
        targets: tuple[tuple[int, int], ...],
        *,
        occupied: set[tuple[int, int]] | None = None,
    ) -> tuple[
        tuple[int, int],
        list[tuple[tuple[int, int], int]],
    ] | None:
        """Return the shortest path to any target cell where the boat fits.

        ``occupied`` lets the caller treat other boats' footprints as
        temporary obstacles so a blocked boat can plan around them.
        """
        if boat.position is None or not targets:
            return None

        directions = (
            DIRECTION_NORTH,
            DIRECTION_EAST,
            DIRECTION_SOUTH,
            DIRECTION_WEST,
        )
        target_set = set(targets)
        start = boat.position
        parents: dict[
            tuple[int, int],
            tuple[tuple[int, int], int] | None,
        ] = {start: None}
        pending = deque([start])

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

        if start in target_set:
            for direction in directions:
                if self._boat_fits_at(
                    boat, start, direction, occupied=occupied
                ):
                    return start, []

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

                if neighbor in target_set:
                    for target_direction in directions:
                        if self._boat_fits_at(
                            boat,
                            neighbor,
                            target_direction,
                            occupied=occupied,
                        ):
                            return (
                                neighbor,
                                path_to(current)
                                + [(neighbor, target_direction)],
                            )

                if neighbor not in parents and self._boat_fits_at(
                    boat, neighbor, direction, occupied=occupied
                ):
                    parents[neighbor] = (current, direction)
                    pending.append(neighbor)

        return None

    def _occupied_cells(
        self, exclude: Boat | None = None
    ) -> set[tuple[int, int]]:
        """Cells currently covered by boats other than ``exclude``."""
        occupied: set[tuple[int, int]] = set()
        for other in self.boats:
            if other is exclude or other.position is None:
                continue
            occupied.update(other.occupied_cells())
        return occupied

    def _release_deposit_target(self, boat: Boat) -> None:
        target = boat.navigation_target
        if target is not None and self.deposit_reservations.get(target) is boat:
            del self.deposit_reservations[target]

    def _assign_deposit(self, boat: Boat) -> bool:
        """Pick a free berth, reserving it so no other boat targets it."""
        old_target = (
            boat.navigation_target if boat.objective == "deposit" else None
        )
        occupied = self._occupied_cells(exclude=boat)
        reserved = {
            cell
            for cell, owner in self.deposit_reservations.items()
            if owner is not boat
        }
        targets = [
            cell
            for cell in self.deposit_access_positions
            if cell not in reserved and cell not in occupied
        ]
        target_info = None
        if targets:
            target_info = self._find_target_path(
                boat, tuple(targets), occupied=occupied
            )
        if target_info is None:
            # Let the boat at least move toward the harbour through a
            # temporary crowd; it will re-plan when it gets blocked.
            free_targets = tuple(
                cell
                for cell in self.deposit_access_positions
                if cell not in reserved
            )
            if free_targets:
                target_info = self._find_target_path(boat, free_targets)
        if target_info is None:
            return False

        target, path = target_info
        if old_target is not None and old_target != target:
            self._release_deposit_target(boat)
        boat.objective = "deposit"
        boat.exit_directions = {}
        self._set_boat_target(boat, target)
        boat.navigation_path = path
        self.deposit_reservations[target] = boat
        return True

    def _assign_fuel(self, boat: Boat) -> bool:
        if not self.fuel_access_positions:
            return False
        self._release_deposit_target(boat)
        boat.objective = "fuel"
        boat.navigation_target = None
        boat.navigation_path = []
        boat.exit_directions = {}
        self._clear_boat_flow_field(boat)
        return True

    def _assign_exit(self, boat: Boat) -> bool:
        if boat.position is None:
            return False

        self._release_deposit_target(boat)
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

        boat.objective = "exit"
        boat.exit_directions = exit_directions
        exit_targets = list(exit_directions) or self.entry_exit_cells
        nearest_exit = min(
            exit_targets,
            key=lambda position: math.dist(boat.position, position),
        )
        self._set_boat_target(boat, nearest_exit, targets=exit_targets)
        return True

    def _update_objective(self, boat: Boat) -> None:
        """Apply the policy: deposit fish, refuel, then leave the map."""
        if boat.fish > 0:
            if (
                boat.objective == "deposit"
                and boat.navigation_target is not None
            ):
                return
            if boat.assignment_cooldown > 0:
                boat.assignment_cooldown -= 1
                return
            if not self._assign_deposit(boat):
                # No free berth right now: hold and retry later.
                boat.objective = None
                boat.navigation_target = None
                boat.navigation_path = []
                self._clear_boat_flow_field(boat)
                boat.assignment_cooldown = 3
            return
        if boat.objective == "exit":
            # Once a boat commits to leaving it does not turn back for fuel.
            return
        if boat.fuel_ratio < self.fuel_threshold and self.fuel_access_positions:
            if boat.objective != "fuel":
                self._assign_fuel(boat)
            return
        self._assign_exit(boat)

    def _clear_boat_flow_field(self, boat: Boat) -> None:
        if boat.flow_field_key is not None:
            self.flow_fields.pop(boat.flow_field_key, None)
        boat.flow_field_key = None

    def _boat_fits_at(
        self,
        boat: Boat,
        position: tuple[int, int],
        direction: int,
        *,
        occupied: set[tuple[int, int]] | None = None,
    ) -> bool:
        previous_direction = boat.direction
        boat.direction = direction
        fits = self.can_place_boat(boat, position)
        if fits and occupied:
            fits = not occupied.intersection(
                boat.occupied_cells(position)
            )
        boat.direction = previous_direction
        return fits

    def _remove_boat(self, boat: Boat) -> None:
        self._release_deposit_target(boat)
        self.grid.remove_agent(boat)
        boat.remove()
        if boat in self.boats:
            self.boats.remove(boat)
        self._clear_boat_flow_field(boat)

    def _rebuild_flow_field(
        self, key: str, targets: tuple[tuple[int, int], ...]
    ) -> None:
        self.flow_fields[key] = (
            generate_flow_field(
                self.grid,
                targets=list(targets),
                is_walkable_func=self.is_cell_walkable,
            )
            if targets
            else {}
        )

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

    def _random_initial_fuel(self) -> float:
        """Fuel left from a boat's trip into the map."""
        ratio = self.random.uniform(
            self.initial_fuel_min_ratio, self.initial_fuel_max_ratio
        )
        return DEFAULT_FUEL_CAPACITY * ratio

    def spawn_boats(self) -> list[Boat]:
        """Spawn scheduled arrivals, retaining boats while the entrance is busy."""
        self._pending_boat_sizes.extend(
            self._arrival_schedule.pop(self.steps, ())
        )

        spawned = []
        pending_count = len(self._pending_boat_sizes)
        for _ in range(pending_count):
            size = self._pending_boat_sizes.popleft()
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
                initial_fuel=self._random_initial_fuel(),
                fish=fish,
            )

            position = self._find_spawn_placement(boat)
            if position is None:
                self._pending_boat_sizes.append(size)
                continue

            self.add_boat(boat, position)
            self.boats_spawned += 1
            spawned.append(boat)
            break
        return spawned

    @staticmethod
    def _objective_priority(boat: Boat) -> int:
        """Fuel-critical boats move first, then loaded, then departing."""
        return {"fuel": 0, "deposit": 1, "exit": 2}.get(boat.objective, 3)

    def _boats_in_priority_order(self) -> list[Boat]:
        return sorted(
            self.boats,
            key=lambda boat: (self._objective_priority(boat), boat.name),
        )

    def _movement_goal(self, boat: Boat) -> tuple[int, int] | None:
        """Approximate goal used to score sidestep moves."""
        if boat.position is None:
            return None
        if boat.objective == "deposit":
            if boat.navigation_target is not None:
                return boat.navigation_target
            candidates = self.deposit_access_positions
        elif boat.objective == "fuel":
            candidates = self.fuel_access_positions
        elif boat.objective == "exit":
            candidates = self.entry_exit_cells
        else:
            return None
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda cell: math.dist(boat.position, cell),
        )

    def _sidestep(self, boat: Boat) -> bool:
        """Take any free cell to break a head-on or footprint deadlock."""
        position = boat.position
        if position is None:
            return False

        occupied = self._occupied_cells(exclude=boat)
        goal = self._movement_goal(boat)
        best: tuple[float, tuple[int, int], int] | None = None
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
            neighbor = (position[0] + dx, position[1] + dy)
            direction = Boat._direction_from_delta(dx, dy)
            if not self._boat_fits_at(
                boat, neighbor, direction, occupied=occupied
            ):
                continue
            score = 0.0
            if goal is not None:
                score = -math.dist(neighbor, goal)
            if best is None or score > best[0]:
                best = (score, neighbor, direction)

        if best is None:
            return False

        _, neighbor, direction = best
        if not self.move_boat(
            boat,
            neighbor[0] - position[0],
            neighbor[1] - position[1],
            direction=direction,
        ):
            return False

        if boat.objective == "deposit":
            # The old path no longer matches the new position. Release the
            # berth so another boat can use it while this one re-plans.
            self._release_deposit_target(boat)
            boat.navigation_target = None
            boat.navigation_path = []
            return True

    def _handle_move_status(self, boat: Boat, status: str) -> None:
        """Wait one turn on a blockage, then re-plan, then step aside."""
        if boat.sidestep_cooldown > 0:
            boat.sidestep_cooldown -= 1

        if status in (MOVE_MOVED, MOVE_ARRIVED):
            boat.blocked_steps = 0
            return
        if status != MOVE_BLOCKED:
            return

        boat.blocked_steps += 1
        if boat.objective == "deposit" and boat.blocked_steps in (2, 5):
            self._assign_deposit(boat)
        if boat.blocked_steps >= 8 and boat.sidestep_cooldown == 0:
            if self._sidestep(boat):
                boat.blocked_steps = 0
                boat.sidestep_cooldown = 4

    def step(self):
        """Update each boat's objective, then move and service it."""
        self.spawn_boats()

        for boat in self._boats_in_priority_order():
            if boat.position is None:
                continue

            self._update_objective(boat)
            if (
                boat.objective == "exit"
                and boat.position in self.entry_exit_cells
            ):
                self._remove_boat(boat)
                continue

            status = boat.step()
            self._handle_move_status(boat, status)
            self.service_boat(boat)

            if (
                boat.objective == "exit"
                and boat.position in self.entry_exit_cells
            ):
                self._remove_boat(boat)

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
        total_minutes = (
            self.SIMULATION_START_HOUR * 60
            + self.steps * 60 // self.STEPS_PER_HOUR
        )
        hours_24, minutes = divmod(total_minutes, 60)
        hours_12 = hours_24 % 12 or 12
        period = "am" if hours_24 < 12 else "pm"
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
        return self.revenue_per_hour * self.SIMULATION_HOURS

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
        zones: set[str] = set()
        for cell in boat.occupied_cells():
            zones |= self.zones_at_position(cell)

        # Every deposit tile is an independent station, so a boat only needs
        # to be next to any deposit zone to unload.
        if "deposit" in zones and boat.fish > 0:
            if self.random.random() < efficiency:
                unloaded = min(
                    boat.fish,
                    max(1, math.ceil(boat.capacity * self.fish_unload_factor)),
                )
                boat.fish -= unloaded
                self.total_fish_deposited += unloaded
                revenue = unloaded * self.fish_price
                self.total_reimbursed_price += revenue
                self.score += revenue
                serviced = True

        if boat.fish <= 0:
            self._release_deposit_target(boat)

        # Only boats whose current objective is refuelling stop for fuel;
        # loaded boats must deposit first.
        if (
            boat.objective == "fuel"
            and "fuel" in zones
            and boat.fuel_ratio < self.fuel_threshold
        ):
            if self.random.random() < efficiency:
                refilled = min(
                    boat.fuel_capacity - boat.fuel,
                    boat.fuel_capacity * self.fuel_refill_factor,
                )
                boat.fuel += refilled
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
