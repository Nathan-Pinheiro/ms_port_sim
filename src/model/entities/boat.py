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
        size : float,
        name : str,
        speed : float,
        capacity : int,
        fuel_consuption : float,
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
        return getattr(self, "pos", None)
