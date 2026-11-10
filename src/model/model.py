from mesa import Model, Agent
from mesa.space import SingleGrid, PropertyLayer

from model.scenario import Scenario
from model.entities.boat import (
    Boat,
    DIRECTION_EAST,
    DIRECTION_NORTH,
    DIRECTION_SOUTH,
    DIRECTION_WEST,
)


class World(Model):
    """Grille de simulation du port.

    Le terrain est une ``PropertyLayer`` dont les valeurs sont :

    * ``0``  – eau navigable
    * ``1``  – terre
    * ``2``  – station carburant
    * ``3``  – station de dépôt
    * ``4``  – case d'entrée / sortie (franchissable, comme l'eau)
    * ``8``  – eau adjacente à une station carburant
    * ``18`` – eau adjacente à une station de dépôt
    """

    fuel_threshold = 25.0
    deposit_access_position = (6, 11)

    WATER = 0
    TERRAIN = 1
    FUEL_STATION = 2
    DEPOSIT_STATION = 3
    ENTRY_EXIT = 4
    FUEL_ADJACENT = 8
    DEPOSIT_ADJACENT = 18

    # Cellules sur lesquelles un bateau peut naviguer (empreinte complète).
    NAVIGABLE = frozenset({WATER, ENTRY_EXIT, FUEL_ADJACENT, DEPOSIT_ADJACENT})

    def __init__(self, scenario: Scenario = Scenario(), demo_boat_fish: int | None = None):
        if scenario.scale < 1 or isinstance(scenario.scale, bool):
            raise ValueError("scenario.scale must be a positive integer")
        if scenario.fish_price < 0 or scenario.fuel_price < 0:
            raise ValueError("fish_price and fuel_price must be non-negative")

        super().__init__(seed=scenario.seed)

        # Paramètres du scénario
        self.ship_spawn_rate = scenario.ship_spawn_rate
        self.fish_amount = scenario.fish_amount
        self.fish_standard_deviation = scenario.fish_standard_deviation
        self.map_scale = scenario.scale
        self.boat_scale = scenario.boat_scale
        self.fish_price = scenario.fish_price
        self.fuel_price = scenario.fuel_price

        # État / compteurs
        self.boats: list[Boat] = []
        self.score = 0.0
        self.total_fish_deposited = 0
        self.total_reimbursed_price = 0.0
        self.total_fuel_refilled = 0.0
        self.total_fuel_paid = 0.0
        self.total_boats_serviced = 0
        self.boats_teleported_to_deposit = 0

        # Construction de la grille
        tiles = self._build_scaled_tiles(scenario.tiles, scenario.scale)
        height = len(tiles)
        width = len(tiles[0])
        self.grid = SingleGrid(width, height, scenario.torus)
        self.grid.add_property_layer(
            PropertyLayer("terrain", width, height, default_value=0, dtype=int)
        )

        terrain_layer = self.grid.properties["terrain"]
        for row_idx, row in enumerate(tiles):
            y = height - 1 - row_idx  # origine matplotlib en bas
            for x, value in enumerate(row):
                terrain_layer.set_cell((x, y), value)

        self.map_data = {
            "width": scenario.width * scenario.scale,
            "height": scenario.height * scenario.scale,
            "scale": scenario.scale,
            "tiles": tiles,
        }

        # Toutes les cases d'entrée/sortie, déduites du terrain
        self.entry_exit_cells = [
            (x, y)
            for x in range(width)
            for y in range(height)
            if terrain_layer.data[y][x] == self.ENTRY_EXIT
        ]
        if not self.entry_exit_cells:
            raise ValueError(
                "Le terrain ne contient aucune case d'entrée/sortie "
                f"(valeur {self.ENTRY_EXIT}). Vérifie PORTO_TILES."
            )
        self.boat_spawn_position = self.entry_exit_cells[0]

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

    # ------------------------------------------------------------------ #
    # Construction du terrain
    # ------------------------------------------------------------------ #

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

        # Cases d'eau adjacentes à une station : on les colore différemment
        height = len(expanded_tiles)
        width = len(expanded_tiles[0])
        for y, row in enumerate(expanded_tiles):
            for x, value in enumerate(row):
                if value != 0:
                    continue
                neighbors = [
                    expanded_tiles[ny][nx]
                    for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                    if 0 <= nx < width
                    and 0 <= ny < height
                    and expanded_tiles[ny][nx] in (2, 3)
                ]
                if neighbors:
                    row[x] = 8 if neighbors[0] == 2 else 18

        return expanded_tiles

    # ------------------------------------------------------------------ #
    # Boucle de simulation
    # ------------------------------------------------------------------ #

    def step(self):
        """Téléporte les bateaux fraîchement spawnés vers le dépôt, puis traite les services."""
        for boat in self.boats:
            if boat.position is None:
                continue

            if boat.position == self.boat_spawn_position:
                self.grid.move_agent(boat, self.deposit_access_position)
                self.boats_teleported_to_deposit += 1
                continue

            self.service_boat(boat)

        self.steps += 1

    def service_boat(self, boat: Boat) -> bool:
        """Dépose le poisson et remplit le carburant si le bateau touche une zone."""
        if boat.position is None:
            return False

        serviced = False
        zones = self.zones_at_position(boat.position)

        if "deposit" in zones and boat.fish > 0:
            boat.fish -= 1
            self.total_fish_deposited += 1
            self.total_reimbursed_price += self.fish_price
            self.score += self.fish_price
            serviced = True

        if "fuel" in zones and boat.fuel < self.fuel_threshold:
            refilled = boat.fuel_capacity - boat.fuel
            boat.fuel = boat.fuel_capacity
            self.total_fuel_refilled += refilled
            self.total_fuel_paid += refilled * self.fuel_price
            self.score -= refilled * self.fuel_price
            serviced = True

        if serviced:
            self.total_boats_serviced += 1
        return serviced

    # ------------------------------------------------------------------ #
    # Placement et déplacement
    # ------------------------------------------------------------------ #

    def can_place_boat(
        self,
        boat: Boat,
        position: tuple[int, int],
        *,
        allow_access: bool = False,
    ) -> bool:
        """Indique si l'empreinte du bateau tient à ``position``.

        Chaque cellule de l'empreinte doit être :

        * dans la grille (un bateau ne sort jamais de l'écran),
        * sur une case navigable : eau (``0``), entrée/sortie (``4``),
          ou eau adjacente à une station (``8`` / ``18``).

        ``allow_access`` autorise en plus la cellule ``deposit_access_position``,
        utilisée uniquement lors du placement initial du bateau de démo.
        """
        terrain_layer = self.grid.properties["terrain"].data
        for cell_x, cell_y in boat.occupied_cells(position):
            if not (0 <= cell_x < self.grid.width and 0 <= cell_y < self.grid.height):
                return False
            if terrain_layer[cell_y][cell_x] in self.NAVIGABLE:
                continue
            if allow_access and (cell_x, cell_y) == self.deposit_access_position:
                continue
            return False
        return True

    def turn_boat(self, boat: Boat, direction: int) -> bool:
        """Tourne le bateau sans le déplacer.

        Le changement est annulé (retourne ``False``) si la nouvelle empreinte
        ne tient pas à la position courante.
        """
        if boat.position is None:
            return False

        previous = boat.direction
        boat.direction = int(direction) % 4
        if not self.can_place_boat(boat, boat.position):
            boat.direction = previous
            return False
        return True

    def _move_boat(
        self,
        boat: Boat,
        dx: int,
        dy: int,
        direction: int | None = None,
    ) -> bool:
        """Déplace le bateau en validant toute son empreinte.

        Si ``direction`` est fourni, le bateau s'oriente d'abord dans cette
        direction : orientation et déplacement sont atomiques.
        """
        position = boat.position
        if position is None:
            return False

        previous_direction = boat.direction
        if direction is not None:
            boat.direction = int(direction) % 4

        target = (position[0] + dx, position[1] + dy)
        if not self.can_place_boat(boat, target):
            boat.direction = previous_direction
            return False

        self.grid.move_agent(boat, target)
        return True

    def move_boat(self, boat: Boat, dx: int, dy: int) -> bool:
        """Déplace le bateau de ``(dx, dy)`` sans changer son orientation."""
        return self._move_boat(boat, dx, dy)

    def move_boat_north(self, boat: Boat) -> bool:
        return self._move_boat(boat, 0, 1, direction=DIRECTION_NORTH)

    def move_boat_south(self, boat: Boat) -> bool:
        return self._move_boat(boat, 0, -1, direction=DIRECTION_SOUTH)

    def move_boat_east(self, boat: Boat) -> bool:
        return self._move_boat(boat, 1, 0, direction=DIRECTION_EAST)

    def move_boat_west(self, boat: Boat) -> bool:
        return self._move_boat(boat, -1, 0, direction=DIRECTION_WEST)

    def add_boat(self, boat: Boat, position: tuple[int, int]) -> Boat:
        """Ajoute un bateau immobile sur une case navigable."""
        if not isinstance(boat, Boat):
            raise TypeError("boat must be a Boat")
        if not self.can_place_boat(boat, position, allow_access=True):
            raise ValueError(
                "boats must be placed on navigable cells (all footprint cells)"
            )

        if getattr(boat, "model", None) is None:
            Agent.__init__(boat, self)
        self.grid.place_agent(boat, position)
        if boat not in self.boats:
            self.boats.append(boat)
        return boat

    # ------------------------------------------------------------------ #
    # Zones de service
    # ------------------------------------------------------------------ #

    def nearby_zones(self, position: tuple[int, int]) -> set[str]:
        """Zones de service adjacentes à ``position`` (exclut la case elle-même)."""
        return self._zones_at(position, include_position=False)

    def zones_at_position(self, position: tuple[int, int]) -> set[str]:
        """Zones de service occupées par ou adjacentes à ``position``."""
        return self._zones_at(position, include_position=True)

    def _zones_at(self, position: tuple[int, int], include_position: bool) -> set[str]:
        x, y = position
        positions = [(x, y)] if include_position else []
        positions.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))

        zones: set[str] = set()
        terrain_data = self.grid.properties["terrain"].data
        for nx, ny in positions:
            if self.grid.out_of_bounds((nx, ny)):
                continue
            terrain = terrain_data[ny][nx]
            if terrain in (self.FUEL_STATION, self.FUEL_ADJACENT):
                zones.add("fuel")
            elif terrain in (self.DEPOSIT_STATION, self.DEPOSIT_ADJACENT):
                zones.add("deposit")
        return zones