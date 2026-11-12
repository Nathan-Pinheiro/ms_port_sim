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
from model.pathfinding import generate_flow_field
from model.scenario import Scenario


class World(Model):
    """Grille de simulation du port.

    Le terrain est une ``PropertyLayer`` dont les valeurs sont :

    * ``0``  eau navigable
    * ``1``  terre
    * ``2``  station de dépôt
    * ``3``  station carburant
    * ``4``  case d'entrée / sortie (franchissable, comme l'eau)
    * ``8``  eau adjacente à une station de dépôt
    * ``18`` eau adjacente à une station carburant
    """

    fuel_threshold = 25.0
    deposit_access_position = (6, 11)

    WATER = 0
    TERRAIN = 1
    FUEL_STATION = 3
    DEPOSIT_STATION = 2
    ENTRY_EXIT = 4
    FUEL_ADJACENT = 18
    DEPOSIT_ADJACENT = 8

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
        self.boats_spawned = 0

        # Champs de vecteurs (flow fields) utilises par le pathfinding
        self.flow_fields: dict = {}

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
            if terrain_layer.data[x][y] == self.ENTRY_EXIT
        ]
        if not self.entry_exit_cells:
            raise ValueError(
                "Le terrain ne contient aucune case d'entrée/sortie "
                f"(valeur {self.ENTRY_EXIT}). Vérifie PORTO_TILES."
            )
        self.boat_spawn_position = self.entry_exit_cells[0]

        # L'agitation est fixe : calculee une fois au demarrage.
        self.agitation = self.compute_agitation()
        agitation_layer = PropertyLayer(
            "agitation", width, height, default_value=0.0, dtype=float
        )
        self.grid.add_property_layer(agitation_layer)
        for x in range(width):
            for y in range(height):
                # NaN = pas de couleur d'agitation (terre/stations) : la case
                # reste transparente au lieu de devenir claire.
                value = (
                    self.agitation[x][y]
                    if terrain_layer.data[x][y] in self.NAVIGABLE
                    else float("nan")
                )
                agitation_layer.set_cell((x, y), value)

        # Le champ de depot doit exister avant le premier pas de simulation.
        self.update_deposit_flow_field()

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
                    # 2 = depot -> acces 8 ; 3 = carburant -> acces 18
                    row[x] = 8 if neighbors[0] == 2 else 18

        return expanded_tiles

    def compute_agitation(self) -> list[list[float]]:
        """Calcule l'agitation de l'eau (0.0 = calme, 1.0 = agité).

        Méthode des « trajets opposés » : pour chaque case d'eau, on regarde la
        direction du premier pas du plus court chemin vers chacune des cases de
        large (les entrées/sorties de la carte). Dans un bassin enclos, tous ces
        chemins sortent par le même chenal : les directions se ressemblent et
        l'écart angulaire maximal reste faible, donc l'eau est calme. En eau
        ouverte, les chemins vers des entrées opposées partent dans des
        directions opposées : l'écart angulaire maximal est grand, donc l'eau
        est agitée.

        Le résultat est indexé ``agitation[x][y]``.
        """
        width = self.grid.width
        height = self.grid.height
        terrain = self.grid.properties["terrain"].data

        # 8 directions, chacune associée à son angle.
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

        # Aplatit les cases navigables pour des parcours en largeur rapides.
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

        # Cases de large : les entrées/sorties, sinon le bord navigable.
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

        # Un sous-échantillon régulier suffit : des entrées voisines donnent des
        # directions quasi identiques. Cela garde le calcul rapide au démarrage.
        stride = max(1, len(open_ids) // 150)
        open_ids = open_ids[::stride]

        # Pour chaque case, masque binaire des directions de sortie observées.
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

            # Direction du premier pas vers cette entrée.
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
                # Le large lui-même est toujours agité.
                agitation[x][y] = 1.0
                continue

            directions = [d for d in range(8) if out_dirs[i] >> d & 1]
            if len(directions) < 2:
                # Une seule direction de sortie : l'eau est enfermée, calme.
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
        """Indique si la case ``(x, y)`` est navigable (independamment d'un bateau)."""
        if self.grid.out_of_bounds((x, y)):
            return False
        terrain = self.grid.properties["terrain"].data[x][y]
        return terrain in self.NAVIGABLE

    def get_available_deposit_positions(self) -> list[tuple[int, int]]:
        """Cases d'eau adjacentes au depot, libres en priorite."""
        available = []
        width = self.grid.width
        height = self.grid.height
        for y in range(height):
            for x in range(width):
                terrain = self.grid.properties["terrain"].data[x][y]
                if terrain == self.DEPOSIT_ADJACENT:
                    if self.grid.is_cell_empty((x, y)):
                        available.append((x, y))

        if not available:
            for y in range(height):
                for x in range(width):
                    terrain = self.grid.properties["terrain"].data[x][y]
                    if terrain == self.DEPOSIT_ADJACENT:
                        available.append((x, y))

        return available

    def update_deposit_flow_field(self) -> None:
        """Recalcule le flow field vers les acces de depot disponibles."""
        targets = self.get_available_deposit_positions()
        if targets:
            self.flow_fields["deposit"] = generate_flow_field(
                self.grid,
                targets=targets,
                is_walkable_func=self.is_cell_walkable,
            )
        else:
            self.flow_fields["deposit"] = {}

    # ------------------------------------------------------------------ #
    # Apparition des bateaux
    # ------------------------------------------------------------------ #

    def _find_spawn_placement(self, boat: Boat) -> tuple[int, int] | None:
        """Trouve une case d'entree libre ou l'empreinte du bateau peut tenir."""
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
                fits = self.can_place_boat(boat, position) and all(
                    self.grid.is_cell_empty(cell)
                    for cell in boat.occupied_cells(position)
                )
                boat.direction = previous_direction
                if fits:
                    placements.append((position, direction))

        if not placements:
            return None

        position, direction = self.random.choice(placements)
        boat.direction = direction
        return position

    def spawn_boats(self) -> list[Boat]:
        """Fait apparaitre un bateau aleatoire sur une entree libre.

        ``ship_spawn_rate`` est la probabilite de spawn par pas de simulation.
        Le poisson embarque suit une loi normale
        ``(fish_amount, fish_standard_deviation)``, bornee a zero.
        """
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
            fuel_consuption=1,
            fish=fish,
        )

        position = self._find_spawn_placement(boat)
        if position is None:
            return []

        self.add_boat(boat, position)
        self.boats_spawned += 1
        return [boat]

    # ------------------------------------------------------------------ #
    # Boucle de simulation
    # ------------------------------------------------------------------ #

    def step(self):
        """Fait apparaitre de nouveaux bateaux puis traite deplacements et services."""
        self.spawn_boats()

        for boat in list(self.boats):
            if boat.position is None:
                continue

            boat.step()

            serviced = self.service_boat(boat)
            if serviced:
                self.update_deposit_flow_field()

        self.steps += 1

    def service_boat(self, boat: Boat) -> bool:
        """Dépose le poisson et remplit le carburant si le bateau touche une zone."""
        if boat.position is None:
            return False

        x, y = boat.position
        agitation = self.agitation[x][y]

        # Efficacité de 1.0 (eau calme) à 0.2 (eau très agitée).
        efficiency = max(0.2, 1.0 - agitation * 0.8)

        serviced = False
        zones = self.zones_at_position(boat.position)

        if "deposit" in zones and boat.fish > 0:
            # En eau agitée, le poisson peut être baladé et le dépôt échoue.
            if self.random.random() < efficiency:
                boat.fish -= 1
                self.total_fish_deposited += 1
                self.total_reimbursed_price += self.fish_price
                self.score += self.fish_price
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
            if terrain_layer[cell_x][cell_y] in self.NAVIGABLE:
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
        if not self.can_place_boat(boat, target) or not self.grid.is_cell_empty(
            target
        ):
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
            terrain = terrain_data[nx][ny]
            if terrain in (self.FUEL_STATION, self.FUEL_ADJACENT):
                zones.add("fuel")
            elif terrain in (self.DEPOSIT_STATION, self.DEPOSIT_ADJACENT):
                zones.add("deposit")
        return zones