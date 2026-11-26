from __future__ import annotations

import math

from mesa import Agent


# Size -> (length along the bow, beam). Length is horizontal when facing east,
# which is the orientation of the SVG assets.
BOAT_FOOTPRINTS: dict[int, tuple[int, int]] = {
    1: (1, 1),
    2: (2, 1),
    3: (3, 2),
}

DEFAULT_BOAT_SIZE = 1
DEFAULT_FUEL_CAPACITY = 100.0

# 0 = north, 1 = east, 2 = south, 3 = west.
DIRECTION_NORTH = 0
DIRECTION_EAST = 1
DIRECTION_SOUTH = 2
DIRECTION_WEST = 3

VERTICAL_DIRECTIONS = (DIRECTION_NORTH, DIRECTION_SOUTH)

# Result of a boat's movement attempt.
MOVE_MOVED = "moved"
MOVE_ARRIVED = "arrived"
MOVE_BLOCKED = "blocked"
MOVE_IDLE = "idle"


class Boat(Agent):
    def __init__(
        self,
        size: float,
        name: str,
        speed: float,
        capacity: int,
        fuel_capacity: float = DEFAULT_FUEL_CAPACITY,
        initial_fuel: float | None = None,
        fish: int = 0,
        boat_type: str = "fisher",
        direction: int = DIRECTION_NORTH,
        model=None,
    ):
        if model is not None:
            super().__init__(model)
        if capacity < 0:
            raise ValueError("capacity must be non-negative")
        if fuel_capacity <= 0:
            raise ValueError("fuel_capacity must be positive")

        self.size: float = size
        self.name: str = name
        self.speed: float = speed
        self.capacity: int = capacity
        self.fuel_capacity: float = fuel_capacity
        self.fuel: float = (
            fuel_capacity if initial_fuel is None else initial_fuel
        )
        self.fish: int = fish
        if not 0 <= self.fuel <= fuel_capacity:
            raise ValueError("initial_fuel must be between zero and fuel_capacity")
        if not 0 <= fish <= capacity:
            raise ValueError("fish must be between zero and capacity")

        self.boat_type: str = boat_type
        self.direction: int = int(direction) % 4
        self.objective: str | None = None
        self.navigation_target: tuple[int, int] | None = None
        self.navigation_path: list[tuple[tuple[int, int], int]] = []
        self.exit_directions: dict[tuple[int, int], int] = {}
        self.flow_field_key: object | None = None
        # Pathfinding feedback, driven by World after every movement attempt.
        self.blocked_steps: int = 0
        self.assignment_cooldown: int = 0
        self.sidestep_cooldown: int = 0

    @property
    def size_key(self) -> int:
        try:
            key = int(round(float(self.size)))
        except (TypeError, ValueError):
            return DEFAULT_BOAT_SIZE
        return key if key in BOAT_FOOTPRINTS else DEFAULT_BOAT_SIZE

    @property
    def heading(self) -> int:
        return int(self.direction) % 4

    @property
    def fuel_ratio(self) -> float:
        """Fuel level as a fraction of capacity, clamped to ``[0, 1]``."""
        return max(0.0, min(1.0, self.fuel / self.fuel_capacity))

    @property
    def footprint(self) -> tuple[int, int]:
        """Footprint as ``(width, height)`` in cells for the current heading."""
        length, beam = BOAT_FOOTPRINTS[self.size_key]
        if self.heading in VERTICAL_DIRECTIONS:
            return beam, length
        return length, beam

    def occupied_cells(
        self, position: tuple[int, int] | None = None
    ) -> list[tuple[int, int]]:
        """Cells covered by the boat, anchored at its bottom-left corner."""
        if position is None:
            position = self.position
        if position is None:
            return []

        x, y = position
        width, height = self.footprint
        return [
            (x + dx, y + dy)
            for dx in range(width)
            for dy in range(height)
        ]

    @property
    def position(self) -> tuple[int, int] | None:
        return self.pos

    def _get_avoidance_vector(self, radius: int = 2) -> tuple[float, float]:
        if self.pos is None:
            return (0.0, 0.0)

        avoid_x, avoid_y = 0.0, 0.0
        neighbors = self.model.grid.get_neighbors(
            self.pos, moore=True, include_center=False, radius=radius
        )

        for neighbor in neighbors:
            if isinstance(neighbor, Boat) and neighbor != self:
                dx = self.pos[0] - neighbor.pos[0]
                dy = self.pos[1] - neighbor.pos[1]
                distance = math.hypot(dx, dy)
                if distance > 0:
                    weight = 1.0 / (distance**2)
                    avoid_x += (dx / distance) * weight
                    avoid_y += (dy / distance) * weight

        return (avoid_x, avoid_y)

    @staticmethod
    def _direction_from_delta(dx: int, dy: int) -> int:
        """Dominant cardinal direction of a ``(dx, dy)`` move."""
        if abs(dx) >= abs(dy):
            return DIRECTION_EAST if dx > 0 else DIRECTION_WEST
        return DIRECTION_NORTH if dy > 0 else DIRECTION_SOUTH

    def _select_best_neighbor_cell(
        self,
        target_dx: float,
        target_dy: float,
    ) -> tuple[int, int] | None:
        if self.pos is None or (target_dx == 0 and target_dy == 0):
            return self.pos

        best_pos = self.pos
        best_score = -float("inf")
        previous_direction = self.direction

        possible_steps = self.model.grid.get_neighborhood(
            self.pos, moore=True, include_center=False
        )

        for nx, ny in possible_steps:
            dir_x = nx - self.pos[0]
            dir_y = ny - self.pos[1]
            length = math.hypot(dir_x, dir_y)
            if length == 0:
                continue

            # Large boats need a valid footprint in the direction of travel.
            direction = self._direction_from_delta(dir_x, dir_y)
            self.direction = direction
            can_place = self.model.can_place_boat(self, (nx, ny))
            if not can_place:
                continue
            if not self.model.can_boat_move_to(self, (nx, ny)):
                continue

            dot_product = ((dir_x / length) * target_dx) + (
                (dir_y / length) * target_dy
            )
            if dot_product > best_score:
                best_score = dot_product
                best_pos = (nx, ny)

        self.direction = previous_direction
        return best_pos

    def _footprint_zones(self) -> set[str]:
        zones: set[str] = set()
        for cell in self.occupied_cells():
            zones |= self.model.zones_at_position(cell)
        return zones

    def _follow_path(self) -> str:
        """Move one step along the boat's fixed navigation path."""
        if not self.navigation_path:
            return MOVE_BLOCKED

        next_pos, direction = self.navigation_path[0]
        previous_direction = self.direction
        self.direction = direction
        can_move = self.model.can_boat_move_to(self, next_pos)
        self.direction = previous_direction
        if not can_move:
            return MOVE_BLOCKED

        dx = next_pos[0] - self.pos[0]
        dy = next_pos[1] - self.pos[1]
        if not self.model.move_boat(self, dx, dy, direction=direction):
            return MOVE_BLOCKED

        self.navigation_path.pop(0)
        return MOVE_MOVED

    def move(self, target_key: str = "deposit") -> str:
        """Attempt one movement step and report what happened."""
        if self.pos is None:
            return MOVE_IDLE

        if target_key == "deposit":
            if (
                self.navigation_target is not None
                and self.pos == self.navigation_target
            ):
                return MOVE_ARRIVED
            if (
                self.navigation_target is None
                and self.fish > 0
                and "deposit" in self._footprint_zones()
            ):
                return MOVE_ARRIVED
            if self.navigation_target is not None:
                return self._follow_path()
            return MOVE_IDLE

        if target_key == "fuel":
            if (
                self.fuel < self.fuel_capacity
                and "fuel" in self._footprint_zones()
            ):
                return MOVE_ARRIVED
        elif target_key == "exit" and self.pos in self.exit_directions:
            return MOVE_ARRIVED

        # Fuel and exit follow a flow field toward every valid target cell.
        flow_fields = getattr(self.model, "flow_fields", {})
        field_key = (
            self.flow_field_key
            if target_key == "exit" and self.flow_field_key is not None
            else target_key
        )
        flow_field = flow_fields.get(field_key, {})
        ff_dx, ff_dy = flow_field.get(self.pos, (0.0, 0.0))

        avoid_dx, avoid_dy = self._get_avoidance_vector(radius=2)
        combined_dx = ff_dx + (avoid_dx * 1.5)
        combined_dy = ff_dy + (avoid_dy * 1.5)

        next_pos = self._select_best_neighbor_cell(
            combined_dx,
            combined_dy,
        )
        if not next_pos or next_pos == self.pos:
            return MOVE_BLOCKED

        dx = next_pos[0] - self.pos[0]
        dy = next_pos[1] - self.pos[1]
        if target_key == "exit" and next_pos in self.exit_directions:
            direction = self.exit_directions[next_pos]
        else:
            direction = self._direction_from_delta(dx, dy)
        if not self.model.move_boat(self, dx, dy, direction=direction):
            return MOVE_BLOCKED
        return MOVE_MOVED

    def step(self) -> str:
        if self.objective is None:
            return MOVE_IDLE
        return self.move(target_key=self.objective)

