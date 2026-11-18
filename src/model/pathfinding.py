from __future__ import annotations

import math
from collections import deque


def generate_flow_field(
    grid,
    targets: list[tuple[int, int]],
    is_walkable_func=None,
) -> dict[tuple[int, int], tuple[float, float]]:
    """Return a unit vector per cell pointing toward the closest target."""
    width = grid.width
    height = grid.height

    distance = {
        (x, y): float("inf") for x in range(width) for y in range(height)
    }
    queue = deque()

    for target in targets:
        distance[target] = 0.0
        queue.append(target)

    directions = [
        (-1, 0),
        (1, 0),
        (0, -1),
        (0, 1),
        (-1, -1),
        (-1, 1),
        (1, -1),
        (1, 1),
    ]

    # Multi-source BFS with diagonal step costs.
    while queue:
        cx, cy = queue.popleft()
        current_distance = distance[(cx, cy)]

        for dx, dy in directions:
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if is_walkable_func and not is_walkable_func(nx, ny):
                continue

            step_cost = 1.414 if dx != 0 and dy != 0 else 1.0
            new_distance = current_distance + step_cost
            if new_distance < distance[(nx, ny)]:
                distance[(nx, ny)] = new_distance
                queue.append((nx, ny))

    flow_field: dict[tuple[int, int], tuple[float, float]] = {}
    for x in range(width):
        for y in range(height):
            position = (x, y)
            if distance[position] == float("inf"):
                flow_field[position] = (0.0, 0.0)
                continue

            best_direction = (0.0, 0.0)
            minimum = distance[position]
            for dx, dy in directions:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                if distance[(nx, ny)] < minimum:
                    minimum = distance[(nx, ny)]
                    best_direction = (float(dx), float(dy))

            length = math.hypot(*best_direction)
            if length > 0:
                flow_field[position] = (
                    best_direction[0] / length,
                    best_direction[1] / length,
                )
            else:
                flow_field[position] = (0.0, 0.0)

    return flow_field
