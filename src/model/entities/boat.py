import math
from mesa import Agent


class Boat(Agent):
    def __init__(
        self,
        size: float,
        name: str,
        speed: float,
        capacity: int,
        fuel_consuption: float,
        fuel_capacity: float = 100.0,
        initial_fuel: float | None = None,
        fish: int = 0,
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
        self.fuel_consuption: float = fuel_consuption
        self.fuel_consumption: float = fuel_consuption
        self.fuel_capacity: float = fuel_capacity
        self.fuel: float = (
            fuel_capacity if initial_fuel is None else initial_fuel
        )
        self.fish: int = fish
        if not 0 <= self.fuel <= fuel_capacity:
            raise ValueError("initial_fuel must be between zero and fuel_capacity")
        if not 0 <= fish <= capacity:
            raise ValueError("fish must be between zero and capacity")

    @property
    def fish_amount(self) -> int:
        return self.fish

    @property
    def fuel_level(self) -> float:
        return self.fuel

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
                dist = math.hypot(dx, dy)
                if dist > 0:
                    weight = 1.0 / (dist**2)
                    avoid_x += (dx / dist) * weight
                    avoid_y += (dy / dist) * weight

        return (avoid_x, avoid_y)

    def _select_best_neighbor_cell(
        self, target_dx: float, target_dy: float
    ) -> tuple[int, int] | None:
        if self.pos is None or (target_dx == 0 and target_dy == 0):
            return self.pos

        best_pos = self.pos
        best_score = -float("inf")

        possible_steps = self.model.grid.get_neighborhood(
            self.pos, moore=True, include_center=False
        )

        for nx, ny in possible_steps:
            if hasattr(self.model, "is_cell_walkable") and not self.model.is_cell_walkable(nx, ny):
                continue

            dir_x = nx - self.pos[0]
            dir_y = ny - self.pos[1]
            length = math.hypot(dir_x, dir_y)
            if length == 0:
                continue

            dot_product = ((dir_x / length) * target_dx) + ((dir_y / length) * target_dy)
            if dot_product > best_score:
                best_score = dot_product
                best_pos = (nx, ny)

        return best_pos

    def move(self, target_key: str = "deposit") -> None:
        if self.pos is None or self.fuel <= 0:
            return

        current_terrain = self.model.grid.properties["terrain"].data[self.pos[0]][self.pos[1]]
        
        if target_key == "deposit":
            # 8 = Case d'eau d'accès au déchargement (Stations Blanches / Haut)
            if current_terrain == 8 and self.fish > 0:
                return
                
        elif target_key == "fuel":
            # 18 = Case d'eau d'accès au carburant (Stations Rouges / Bas)
            if current_terrain == 18 and self.fuel < self.fuel_capacity:
                return

        flow_fields = getattr(self.model, "flow_fields", {})
        flow_field = flow_fields.get(target_key, {})
        ff_dx, ff_dy = flow_field.get(self.pos, (0.0, 0.0))

        avoid_dx, avoid_dy = self._get_avoidance_vector(radius=2)
        combined_dx = ff_dx + (avoid_dx * 1.5)
        combined_dy = ff_dy + (avoid_dy * 1.5)

        next_pos = self._select_best_neighbor_cell(combined_dx, combined_dy)

        if next_pos and next_pos != self.pos:
            self.model.grid.move_agent(self, next_pos)
            self.fuel = max(0.0, self.fuel - self.fuel_consumption)

    def step(self) -> None:
        self.move(target_key="deposit")