"""Area maps and port configurations.

An area map stores the natural layout: ``0`` water, ``1`` earth and ``2``
entry/exit. A port configuration stores what is built on top of it: ``0``
empty, ``5`` artificial land, ``6`` deposit and ``7`` fuel.

Files live in ``data/maps`` and ``data/ports``. A configuration is named
``<map_name>_<port_config_name>.json`` and references its map. At start-up
:func:`fuse_tiles` overlays both layers into the terrain grid used by the
simulation.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAPS_DIR = ROOT / "data" / "maps"
PORTS_DIR = ROOT / "data" / "ports"

AREA_WATER = 0
AREA_EARTH = 1
AREA_ENTRY_EXIT = 2

PORT_EMPTY = 0
PORT_ARTIFICIAL_LAND = 5
PORT_DEPOSIT = 6
PORT_FUEL = 7

AREA_CODES = frozenset({AREA_WATER, AREA_EARTH, AREA_ENTRY_EXIT})
PORT_CODES = frozenset(
    {PORT_EMPTY, PORT_ARTIFICIAL_LAND, PORT_DEPOSIT, PORT_FUEL}
)

WATER = 0
TERRAIN = 1
DEPOSIT_STATION = 2
FUEL_STATION = 3
ENTRY_EXIT = 4
ARTIFICIAL_LAND = 5


class MapError(ValueError):
    """Raised when a map or a port configuration is invalid."""


def _validate_rectangular(tiles: list[list[int]], label: str) -> None:
    if not tiles:
        raise MapError(f"{label} must not be empty")
    width = len(tiles[0])
    if width == 0:
        raise MapError(f"{label} rows must not be empty")
    if any(len(row) != width for row in tiles):
        raise MapError(f"{label} must be a rectangular grid")


def validate_area_tiles(tiles: list[list[int]]) -> None:
    _validate_rectangular(tiles, "Area map")
    for row in tiles:
        for value in row:
            if value not in AREA_CODES:
                raise MapError(
                    f"Invalid area tile {value!r}: expected one of "
                    f"{sorted(AREA_CODES)}"
                )


def validate_port_tiles(tiles: list[list[int]]) -> None:
    _validate_rectangular(tiles, "Port configuration")
    for row in tiles:
        for value in row:
            if value not in PORT_CODES:
                raise MapError(
                    f"Invalid port tile {value!r}: expected one of "
                    f"{sorted(PORT_CODES)}"
                )


def fuse_tiles(
    area_tiles: list[list[int]] | tuple[tuple[int, ...], ...],
    port_tiles: list[list[int]] | tuple[tuple[int, ...], ...],
) -> tuple[tuple[int, ...], ...]:
    """Overlay the port configuration on the area map."""
    area = [list(row) for row in area_tiles]
    port = [list(row) for row in port_tiles]
    validate_area_tiles(area)
    validate_port_tiles(port)
    if len(area) != len(port) or len(area[0]) != len(port[0]):
        raise MapError(
            "The port configuration must have the same size as the area map"
        )

    fused: list[tuple[int, ...]] = []
    for area_row, port_row in zip(area, port):
        fused_row: list[int] = []
        for area_value, port_value in zip(area_row, port_row):
            if port_value == PORT_ARTIFICIAL_LAND:
                fused_row.append(ARTIFICIAL_LAND)
            elif port_value == PORT_DEPOSIT:
                fused_row.append(DEPOSIT_STATION)
            elif port_value == PORT_FUEL:
                fused_row.append(FUEL_STATION)
            elif area_value == AREA_ENTRY_EXIT:
                fused_row.append(ENTRY_EXIT)
            else:
                fused_row.append(area_value)
        fused.append(tuple(fused_row))
    return tuple(fused)


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise MapError(f"File not found: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise MapError(f"Invalid JSON in {path}: {exc}") from exc


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def map_path(map_name: str) -> Path:
    return MAPS_DIR / f"{map_name}.json"


def port_path(map_name: str, config_name: str) -> Path:
    return PORTS_DIR / f"{map_name}_{config_name}.json"


def load_map(map_name: str) -> dict:
    payload = _read_json(map_path(map_name))
    tiles = payload.get("tiles")
    if tiles is None:
        raise MapError(f"Map {map_name!r} has no 'tiles'")
    validate_area_tiles(tiles)
    return payload


def load_port_config(map_name: str, config_name: str) -> dict:
    payload = _read_json(port_path(map_name, config_name))
    tiles = payload.get("tiles")
    if tiles is None:
        raise MapError(
            f"Port configuration {map_name}_{config_name} has no 'tiles'"
        )
    validate_port_tiles(tiles)
    if payload.get("map") not in (None, map_name):
        raise MapError(
            f"Port configuration {map_name}_{config_name} references map "
            f"{payload.get('map')!r}, expected {map_name!r}"
        )
    return payload


def save_port_config(
    map_name: str,
    config_name: str,
    tiles: list[list[int]],
) -> Path:
    tiles = [list(row) for row in tiles]
    validate_port_tiles(tiles)
    map_payload = load_map(map_name)
    if len(tiles) != len(map_payload["tiles"]) or len(tiles[0]) != len(
        map_payload["tiles"][0]
    ):
        raise MapError(
            "The port configuration must have the same size as the area map"
        )
    payload = {
        "name": config_name,
        "map": map_name,
        "width": len(tiles[0]),
        "height": len(tiles),
        "tiles": tiles,
    }
    path = port_path(map_name, config_name)
    _write_json(path, payload)
    return path


def list_maps() -> list[str]:
    if not MAPS_DIR.exists():
        return []
    return sorted(path.stem for path in MAPS_DIR.glob("*.json"))


def list_port_configs(map_name: str) -> list[str]:
    if not PORTS_DIR.exists():
        return []
    prefix = f"{map_name}_"
    return sorted(
        path.stem[len(prefix):]
        for path in PORTS_DIR.glob(f"{prefix}*.json")
    )


def empty_port_tiles(width: int, height: int) -> list[list[int]]:
    return [[PORT_EMPTY] * width for _ in range(height)]
