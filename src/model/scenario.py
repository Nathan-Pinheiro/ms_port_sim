from dataclasses import dataclass

# Fraction of a boat's capacity handled per successful service step.
DEFAULT_FISH_UNLOAD_FACTOR = 0.04
DEFAULT_FUEL_REFILL_FACTOR = 0.02


@dataclass(frozen=True)
class Scenario:
    """Simulation parameters.

    By default the terrain is loaded from the named map and port configuration
    in ``data/``. Tests can pass ``area_tiles`` and ``port_tiles`` directly.
    """

    map_name: str = "matosinhos"
    port_config_name: str = "default"
    area_tiles: tuple[tuple[int, ...], ...] | None = None
    port_tiles: tuple[tuple[int, ...], ...] | None = None
    scale: int = 3
    torus: bool = False
    ship_spawn_rate: float = 0.04
    fish_amount: int = 50
    fish_standard_deviation: float = 5.0
    fish_price: float = 1.0
    fuel_price: float = 1.0
    fish_unload_factor: float = DEFAULT_FISH_UNLOAD_FACTOR
    fuel_refill_factor: float = DEFAULT_FUEL_REFILL_FACTOR
    # Fuel remaining from the trip into the map, as a fraction of capacity.
    # Randomised per boat; every arrival is below the refuel threshold.
    initial_fuel_min_ratio: float = 0.1
    initial_fuel_max_ratio: float = 0.9
    fuel_station_construction_cost: int = 10_000_000
    deposit_station_construction_cost: int = 20_000_000
    boat_scale: float = 1.0
    seed: int | None = None
