from __future__ import annotations

import random


PORT_TYPE_LABELS = {
    "local": "Petit port local / abri",
    "regional": "Port régional moyen",
    "structured": "Grand port de pêche structuré",
}

DEFAULT_PORT_TYPE = "regional"

BOAT_SIZE_LABELS = {
    1: "petits bateaux (côtier / artisanal, < 12–15 m)",
    2: "moyens bateaux (chalutier côtier / senneur, ~15–24 m)",
    3: "grands bateaux (hauturier / congélateur, 24 m+)",
}

PORT_DAILY_ARRIVALS: dict[str, dict[int, tuple[int, int]]] = {
    "local": {
        1: (5, 15),
        2: (0, 3),
        3: (0, 0),
    },
    "regional": {
        1: (15, 40),
        2: (5, 15),
        3: (1, 4),
    },
    "structured": {
        1: (30, 80),
        2: (15, 35),
        3: (4, 12),
    },
}

# Two broad landing peaks: early morning and mid-to-late afternoon.
HOURLY_ARRIVAL_WEIGHTS = (
    1, 1, 1, 1, 2, 4, 8, 10, 9, 6, 4, 3,
    3, 3, 4, 7, 9, 8, 5, 3, 2, 1, 1, 1,
)


def build_daily_arrival_schedule(
    port_type: str,
    rng: random.Random,
    *,
    steps_per_hour: int,
    simulation_start_hour: int,
    simulation_end_hour: int,
) -> dict[int, list[int]]:
    if port_type not in PORT_DAILY_ARRIVALS:
        raise ValueError(f"Unknown port type: {port_type}")
    if steps_per_hour <= 0:
        raise ValueError("steps_per_hour must be positive")
    if not (
        0 <= simulation_start_hour < simulation_end_hour
        <= len(HOURLY_ARRIVAL_WEIGHTS)
    ):
        raise ValueError("Simulation window is outside the arrival profile")

    active_hours = range(simulation_start_hour, simulation_end_hour)
    hourly_weights = [
        HOURLY_ARRIVAL_WEIGHTS[hour] for hour in active_hours
    ]
    schedule: dict[int, list[int]] = {}
    for size, (minimum, maximum) in PORT_DAILY_ARRIVALS[port_type].items():
        for _ in range(rng.randint(minimum, maximum)):
            hour = rng.choices(
                active_hours,
                weights=hourly_weights,
                k=1,
            )[0]
            step = (
                (hour - simulation_start_hour) * steps_per_hour
                + rng.randrange(steps_per_hour)
            )
            schedule.setdefault(step, []).append(size)
    return schedule
