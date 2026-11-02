from mesa import Agent


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