from collections import deque
import math

def generate_flow_field(grid, targets: list[tuple[int, int]], is_walkable_func=None) -> dict[tuple[int, int], tuple[float, float]]:
    """
    Génère un champ de vecteurs (Flow Field) orienté vers les positions cibles.
    
    :param grid: Grille Mesa (MultiGrid ou SingleGrid).
    :param targets: Liste des coordonnées (x, y) des cibles (ex: zones de déchargement).
    :param is_walkable_func: Fonction optionnelle (x, y) -> bool pour vérifier si une case est praticable (ex: eau).
    :return: Dictionnaire {(x, y): (dx, dy)} contenant les vecteurs directionnels unifés.
    """
    width = grid.width
    height = grid.height
    
    # 1. Carte des distances initialisée à l'infini
    distance_map = {(x, y): float('inf') for x in range(width) for y in range(height)}
    queue = deque()

    # Initialisation des sources
    for target in targets:
        distance_map[target] = 0.0
        queue.append(target)

    directions = [
        (-1, 0), (1, 0), (0, -1), (0, 1),      # Cardinaux
        (-1, -1), (-1, 1), (1, -1), (1, 1)     # Diagonales
    ]

    # 2. Algorithme BFS multi-sources pour calculer les distances optimales
    while queue:
        cx, cy = queue.popleft()
        current_dist = distance_map[(cx, cy)]

        for dx, dy in directions:
            nx, ny = cx + dx, cy + dy

            if 0 <= nx < width and 0 <= ny < height:
                if is_walkable_func and not is_walkable_func(nx, ny):
                    continue

                step_cost = 1.414 if (dx != 0 and dy != 0) else 1.0
                new_dist = current_dist + step_cost

                if new_dist < distance_map[(nx, ny)]:
                    distance_map[(nx, ny)] = new_dist
                    queue.append((nx, ny))

    # 3. Conversion de la carte de distance en champ de vecteurs
    flow_field = {}
    for x in range(width):
        for y in range(height):
            pos = (x, y)

            if distance_map[pos] == float('inf'):
                flow_field[pos] = (0.0, 0.0)
                continue

            best_dir = (0.0, 0.0)
            min_dist = distance_map[pos]

            for dx, dy in directions:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    if distance_map[(nx, ny)] < min_dist:
                        min_dist = distance_map[(nx, ny)]
                        best_dir = (float(dx), float(dy))

            # Normalisation du vecteur
            length = math.hypot(best_dir[0], best_dir[1])
            if length > 0:
                flow_field[pos] = (best_dir[0] / length, best_dir[1] / length)
            else:
                flow_field[pos] = (0.0, 0.0)

    return flow_field