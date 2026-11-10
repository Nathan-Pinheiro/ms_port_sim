import math
from mesa import Agent


# Empreinte de base (longueur, largeur) en cellules pour chaque taille.
#
# * ``longueur`` est l'axe proue-poupe lorsque le bateau pointe vers l'Est,
#   c'est-a-dire l'orientation de base des fichiers SVG.
# * ``largeur`` est l'axe perpendiculaire (le travers).
#
# C'est la seule source de verite pour la geometrie des bateaux : le rendu
# (boat_portrayal) et les deplacements (World) l'utilisent tous les deux.
BOAT_FOOTPRINTS: dict[int, tuple[int, int]] = {
    1: (1, 1),  # petit 1x1
    2: (2, 1),  # moyen 2x1
    3: (3, 2),  # grand 3x2
}

DEFAULT_BOAT_SIZE = 1

# Directions : 0=Nord (haut), 1=Est (droite), 2=Sud (bas), 3=Ouest (gauche).
DIRECTION_NORTH = 0
DIRECTION_EAST = 1
DIRECTION_SOUTH = 2
DIRECTION_WEST = 3

# Directions pour lesquelles la longueur du bateau est verticale.
VERTICAL_DIRECTIONS = (DIRECTION_NORTH, DIRECTION_SOUTH)


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

        self.boat_type: str = boat_type
        self.direction: int = int(direction) % 4  # 0=N, 1=E, 2=S, 3=W

    # ------------------------------------------------------------------
    # Empreinte / orientation
    # ------------------------------------------------------------------

    @property
    def size_key(self) -> int:
        """Taille normalisee (1, 2 ou 3), tolerant les valeurs flottantes."""
        try:
            key = int(round(float(self.size)))
        except (TypeError, ValueError):
            return DEFAULT_BOAT_SIZE
        return key if key in BOAT_FOOTPRINTS else DEFAULT_BOAT_SIZE

    @property
    def heading(self) -> int:
        """Direction normalisee dans [0, 3]."""
        return int(self.direction) % 4

    @property
    def footprint(self) -> tuple[int, int]:
        """Empreinte (largeur, hauteur) en cellules selon l'orientation.

        La largeur est l'axe horizontal (x) et la hauteur l'axe vertical (y).
        Un bateau 2x1 oriente au Nord occupe donc 1 cellule en largeur et
        2 en hauteur.
        """
        length, beam = BOAT_FOOTPRINTS[self.size_key]
        if self.heading in VERTICAL_DIRECTIONS:
            return beam, length
        return length, beam

    def occupied_cells(self, position: tuple[int, int] | None = None) -> list[tuple[int, int]]:
        """Cellules occupees par le bateau dont le coin bas-gauche est ``position``.

        Par defaut, utilise la position courante de l'agent. La position de
        l'agent represente toujours le coin bas-gauche de son empreinte.
        """
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

    # ------------------------------------------------------------------
    # Etat
    # ------------------------------------------------------------------

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

    @staticmethod
    def _direction_from_delta(dx: int, dy: int) -> int:
        """Direction cardinale dominante d'un deplacement ``(dx, dy)``."""
        if abs(dx) >= abs(dy):
            return DIRECTION_EAST if dx > 0 else DIRECTION_WEST
        return DIRECTION_NORTH if dy > 0 else DIRECTION_SOUTH

    def _select_best_neighbor_cell(
        self, target_dx: float, target_dy: float
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

            # Un grand bateau doit pouvoir tourner pour emprunter la case :
            # on valide l'empreinte dans la direction du deplacement.
            self.direction = self._direction_from_delta(dir_x, dir_y)
            can_move = self.model.can_place_boat(self, (nx, ny))
            if not can_move:
                continue

            dot_product = ((dir_x / length) * target_dx) + ((dir_y / length) * target_dy)
            if dot_product > best_score:
                best_score = dot_product
                best_pos = (nx, ny)

        self.direction = previous_direction
        return best_pos

    def move(self, target_key: str = "deposit") -> None:
        if self.pos is None or self.fuel <= 0:
            return

        current_terrain = self.model.grid.properties["terrain"].data[
            self.pos[0]
        ][self.pos[1]]

        if target_key == "deposit":
            # 18 = eau adjacente a une station de depot
            if current_terrain == self.model.DEPOSIT_ADJACENT and self.fish > 0:
                return
        elif target_key == "fuel":
            # 8 = eau adjacente a une station carburant
            if (
                current_terrain == self.model.FUEL_ADJACENT
                and self.fuel < self.fuel_capacity
            ):
                return

        flow_fields = getattr(self.model, "flow_fields", {})
        flow_field = flow_fields.get(target_key, {})
        ff_dx, ff_dy = flow_field.get(self.pos, (0.0, 0.0))

        avoid_dx, avoid_dy = self._get_avoidance_vector(radius=2)
        combined_dx = ff_dx + (avoid_dx * 1.5)
        combined_dy = ff_dy + (avoid_dy * 1.5)

        next_pos = self._select_best_neighbor_cell(combined_dx, combined_dy)

        if next_pos and next_pos != self.pos:
            dx = next_pos[0] - self.pos[0]
            dy = next_pos[1] - self.pos[1]
            direction = self._direction_from_delta(dx, dy)
            if self.model._move_boat(self, dx, dy, direction=direction):
                self.fuel = max(0.0, self.fuel - self.fuel_consumption)

    def step(self) -> None:
        self.move(target_key="deposit")
