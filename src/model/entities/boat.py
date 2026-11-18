from __future__ import annotations

import math
from typing import TYPE_CHECKING

from mesa import Agent

if TYPE_CHECKING:
    from model.tiles.deposit_zone import DepositZone


# Size -> (length along the bow, beam). Length is horizontal when facing east,
# which is the orientation of the SVG assets.
BOAT_FOOTPRINTS: dict[int, tuple[int, int]] = {
    1: (1, 1),
    2: (2, 1),
    3: (3, 2),
}

DEFAULT_BOAT_SIZE = 1

# 0 = north, 1 = east, 2 = south, 3 = west.
DIRECTION_NORTH = 0
DIRECTION_EAST = 1
DIRECTION_SOUTH = 2
DIRECTION_WEST = 3

VERTICAL_DIRECTIONS = (DIRECTION_NORTH, DIRECTION_SOUTH)


class Boat(Agent):
    def __init__(
        self,
        size: float,
        name: str,
        speed: float,
        capacity: int,
        fuel_consumption: float,
        fuel_capacity: float = 100.0,
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
        self.fuel_consumption: float = fuel_consumption
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
        self.deposit_station: DepositZone | None = None
        self.deposit_status = "arriving"
        self.navigation_target: tuple[int, int] | None = None
        self.navigation_direction: int | None = None
        self.navigation_path: list[tuple[tuple[int, int], int]] = []
        self.exit_directions: dict[tuple[int, int], int] = {}
        self.flow_field_key: object | None = None

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
        *,
        stop_if_blocked: bool = False,
    ) -> tuple[int, int] | None:
        if self.pos is None or (target_dx == 0 and target_dy == 0):
            return self.pos

        best_pos = self.pos
        best_direction = self.direction
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
            if (
                stop_if_blocked
                and (nx, ny) == self.navigation_target
                and self.navigation_direction is not None
            ):
                direction = self.navigation_direction
            self.direction = direction
            can_place = self.model.can_place_boat(self, (nx, ny))
            if not can_place:
                continue
            if not stop_if_blocked and not self.model.can_boat_move_to(
                self, (nx, ny)
            ):
                continue

            dot_product = ((dir_x / length) * target_dx) + (
                (dir_y / length) * target_dy
            )
            if dot_product > best_score:
                best_score = dot_product
                best_pos = (nx, ny)
                best_direction = direction

        self.direction = previous_direction
        if stop_if_blocked and best_pos != self.pos:
            self.direction = best_direction
            can_move = self.model.can_boat_move_to(self, best_pos)
            self.direction = previous_direction
            if not can_move:
                return self.pos
        return best_pos

    def move(self, target_key: str = "deposit") -> None:
        can_limp_to_deposit = (
            target_key == "deposit" and self.deposit_station is not None
        )
        if (
            self.pos is None
            or (
                self.fuel <= 0
                and target_key != "exit"
                and not can_limp_to_deposit
            )
        ):
            return

        current_terrain = self.model.grid.properties["terrain"].data[
            self.pos[0]
        ][self.pos[1]]

        if target_key == "deposit":
            if (
                self.navigation_target is not None
                and self.pos == self.navigation_target
            ):
                return
            if (
                self.navigation_target is None
                and current_terrain == self.model.DEPOSIT_ADJACENT
                and self.fish > 0
            ):
                return
            if self.navigation_target is not None:
                if not self.navigation_path:
                    return

                next_pos, direction = self.navigation_path[0]
                previous_direction = self.direction
                self.direction = direction
                can_move = self.model.can_boat_move_to(self, next_pos)
                self.direction = previous_direction
                if not can_move:
                    return

                dx = next_pos[0] - self.pos[0]
                dy = next_pos[1] - self.pos[1]
                if self.model.move_boat(self, dx, dy, direction=direction):
                    self.navigation_path.pop(0)
                    self.fuel = max(
                        0.0, self.fuel - self.fuel_consumption
                    )
                return
        elif target_key == "fuel":
            if (
                current_terrain == self.model.FUEL_ADJACENT
                and self.fuel < self.fuel_capacity
            ):
                return

        flow_fields = getattr(self.model, "flow_fields", {})
        field_key = (
            self.flow_field_key
            if target_key in ("deposit", "exit")
            and self.flow_field_key is not None
            else target_key
        )
        flow_field = flow_fields.get(field_key, {})
        ff_dx, ff_dy = flow_field.get(self.pos, (0.0, 0.0))

        fixed_deposit_route = (
            target_key == "deposit" and self.navigation_target is not None
        )
        if fixed_deposit_route:
            avoid_dx, avoid_dy = 0.0, 0.0
        else:
            avoid_dx, avoid_dy = self._get_avoidance_vector(radius=2)
        combined_dx = ff_dx + (avoid_dx * 1.5)
        combined_dy = ff_dy + (avoid_dy * 1.5)

        next_pos = self._select_best_neighbor_cell(
            combined_dx,
            combined_dy,
            stop_if_blocked=fixed_deposit_route,
        )

        if next_pos and next_pos != self.pos:
            dx = next_pos[0] - self.pos[0]
            dy = next_pos[1] - self.pos[1]
            if target_key == "exit" and next_pos in self.exit_directions:
                direction = self.exit_directions[next_pos]
            elif (
                target_key == "deposit"
                and next_pos == self.navigation_target
                and self.navigation_direction is not None
            ):
                direction = self.navigation_direction
            else:
                direction = self._direction_from_delta(dx, dy)
            if self.model.move_boat(self, dx, dy, direction=direction):
                self.fuel = max(0.0, self.fuel - self.fuel_consumption)

    def step(self) -> None:
        target_key = "exit" if self.deposit_status == "exiting" else "deposit"
        self.move(target_key=target_key)
