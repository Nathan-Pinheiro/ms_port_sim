"""Vector rendering of the boats for the Matplotlib/Solara dashboard.

Mesa image markers ignore the colour given in ``AgentPortrayalStyle``, so
boats are drawn as ``PathPatch`` objects built from the SVG assets. The colour
can then be recomputed on every frame, and the boat exactly fills its cell
footprint.
"""

from __future__ import annotations

import colorsys
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath

from model.entities.boat import BOAT_FOOTPRINTS, Boat

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources" / "boats"

DEFAULT_MAX_FISH = 100
WHITE_LIGHTNESS = 0.97

TYPE_COLORS: dict[str, str] = {
    "fisher": "#ef0505",
    "transport": "#ff7f0e",
    "cargo": "#2ca02c",
    "default": "#1f77b4",
}

BOAT_SKINS: dict[int, str] = {
    1: "small_boat.svg",
    2: "medium_boat.svg",
    3: "large_boat.svg",
}
DEFAULT_SKIN_KEY = 1

SVG_COLOR_PLACEHOLDERS: dict[str, str] = {
    "{color}": "main",
    "{main_color}": "main",
    "{inner_color}": "inner",
    "{detail_color}": "detail",
}

# Base SVGs face east; these rotations make them face each direction.
DIRECTION_ROTATION_DEG: dict[int, float] = {
    0: 90.0,
    1: 0.0,
    2: -90.0,
    3: 180.0,
}

BOAT_ZORDER = 3

# Parsed SVGs never change while the app runs.
_SVG_ELEMENTS_CACHE: dict[str, tuple[list[tuple], float, float]] = {}

_CMD_RE = re.compile(r"([MLCSHVQZmlcshvqz])")
_NUM_RE = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_ARGS: dict[str, int] = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Q": 4, "Z": 0}


def _tokenize_path_data(d: str) -> list[tuple[str, str | float]]:
    tokens: list[tuple[str, str | float]] = []
    pos = 0
    length = len(d)
    while pos < length:
        match = _CMD_RE.match(d, pos)
        if match:
            tokens.append(("cmd", match.group(1)))
            pos = match.end()
            continue
        match = re.match(_NUM_RE, d[pos:])
        if match:
            tokens.append(("num", float(match.group(0))))
            pos += match.end()
            continue
        pos += 1
    return tokens


def _parse_path_data(d: str) -> tuple[list[list[float]], list[int]] | None:
    tokens = _tokenize_path_data(d)
    verts: list[list[float]] = []
    codes: list[int] = []
    cur_x = cur_y = 0.0
    start_x = start_y = 0.0
    i = 0
    n = len(tokens)
    while i < n:
        kind, val = tokens[i]
        if kind != "cmd":
            i += 1
            continue
        cmd = val.upper()
        is_rel = val.islower()
        n_args = _ARGS.get(cmd, 0)
        args: list[float] = []
        j = i + 1
        while len(args) < n_args and j < n and tokens[j][0] == "num":
            args.append(tokens[j][1])  # type: ignore[arg-type]
            j += 1
        if len(args) < n_args:
            i = j
            continue
        if cmd == "M":
            x, y = args[0], args[1]
            if is_rel:
                x += cur_x
                y += cur_y
            verts.append([x, y])
            codes.append(MplPath.MOVETO)
            cur_x, cur_y = x, y
            start_x, start_y = x, y
            k = 2
            while k + 1 < len(args):
                x, y = args[k], args[k + 1]
                if is_rel:
                    x += cur_x
                    y += cur_y
                verts.append([x, y])
                codes.append(MplPath.LINETO)
                cur_x, cur_y = x, y
                k += 2
        elif cmd == "L":
            for k in range(0, len(args), 2):
                x, y = args[k], args[k + 1]
                if is_rel:
                    x += cur_x
                    y += cur_y
                verts.append([x, y])
                codes.append(MplPath.LINETO)
                cur_x, cur_y = x, y
        elif cmd == "H":
            for x in args:
                if is_rel:
                    x += cur_x
                verts.append([x, cur_y])
                codes.append(MplPath.LINETO)
                cur_x = x
        elif cmd == "V":
            for y in args:
                if is_rel:
                    y += cur_y
                verts.append([cur_x, y])
                codes.append(MplPath.LINETO)
                cur_y = y
        elif cmd == "C":
            for k in range(0, len(args), 6):
                x1, y1, x2, y2, x, y = args[k : k + 6]
                if is_rel:
                    x1 += cur_x
                    y1 += cur_y
                    x2 += cur_x
                    y2 += cur_y
                    x += cur_x
                    y += cur_y
                verts.append([x1, y1])
                codes.append(MplPath.CURVE4)
                verts.append([x2, y2])
                codes.append(MplPath.CURVE4)
                verts.append([x, y])
                codes.append(MplPath.CURVE4)
                cur_x, cur_y = x, y
        elif cmd == "Q":
            for k in range(0, len(args), 4):
                x1, y1, x, y = args[k : k + 4]
                if is_rel:
                    x1 += cur_x
                    y1 += cur_y
                    x += cur_x
                    y += cur_y
                verts.append([x1, y1])
                codes.append(MplPath.CURVE3)
                verts.append([x, y])
                codes.append(MplPath.CURVE3)
                cur_x, cur_y = x, y
        elif cmd == "Z":
            verts.append([cur_x, cur_y])
            codes.append(MplPath.CLOSEPOLY)
            cur_x, cur_y = start_x, start_y
        i = j
    if not verts:
        return None
    return verts, codes


def _rect_to_path(
    x: float, y: float, w: float, h: float
) -> tuple[list[list[float]], list[int]]:
    """Convert an SVG ``<rect>`` to matplotlib vertices and codes."""
    verts = [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]
    codes = [
        MplPath.MOVETO,
        MplPath.LINETO,
        MplPath.LINETO,
        MplPath.LINETO,
        MplPath.CLOSEPOLY,
    ]
    return verts, codes


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _parse_svg_elements(
    svg_path: Path | str,
) -> tuple[list[tuple], float, float] | None:
    """Return ``(drawables, viewbox_width, viewbox_height)`` for an SVG.

    Each drawable is ``(verts, codes, fill, stroke, stroke_width)`` in SVG
    coordinates; colour placeholders are resolved when drawing.
    """
    key = str(svg_path)
    cached = _SVG_ELEMENTS_CACHE.get(key)
    if cached is not None:
        return cached

    try:
        tree = ET.parse(key)
    except (ET.ParseError, FileNotFoundError, OSError):
        return None
    root = tree.getroot()

    viewbox = root.get("viewBox", "0 0 100 100")
    parts = [float(p) for p in viewbox.split()]
    if len(parts) == 4:
        _, _, vb_w, vb_h = parts
    else:
        vb_w, vb_h = 100.0, 100.0

    drawables: list[tuple] = []
    for element in root.iter():
        tag = _local_tag(element.tag)
        if tag == "path":
            d = element.get("d")
            if not d:
                continue
            parsed = _parse_path_data(d)
            if parsed is None:
                continue
            verts, codes = parsed
        elif tag == "rect":
            verts, codes = _rect_to_path(
                float(element.get("x", "0")),
                float(element.get("y", "0")),
                float(element.get("width", "0")),
                float(element.get("height", "0")),
            )
        else:
            continue

        drawables.append(
            (
                verts,
                codes,
                element.get("fill", "none"),
                element.get("stroke", "none"),
                float(element.get("stroke-width", "1")),
            )
        )

    result = (drawables, vb_w, vb_h)
    _SVG_ELEMENTS_CACHE[key] = result
    return result


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    return tuple(
        int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4)
    )


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % tuple(
        int(max(0, min(255, round(c * 255)))) for c in rgb
    )


def tint_boat_color(
    base_hex: str,
    fish_ratio: float,
    white_lightness: float = WHITE_LIGHTNESS,
) -> str:
    """Fade a boat toward white as it empties, keeping its hue."""
    ratio = max(0.0, min(1.0, fish_ratio))
    r, g, b = _hex_to_rgb(base_hex)
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    new_saturation = saturation * ratio
    new_lightness = white_lightness * (1.0 - ratio) + lightness * ratio
    r2, g2, b2 = colorsys.hls_to_rgb(hue, new_lightness, new_saturation)
    return _rgb_to_hex((r2, g2, b2))


def _color_variants(main_hex: str) -> dict[str, str]:
    r, g, b = _hex_to_rgb(main_hex)
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    inner = colorsys.hls_to_rgb(
        hue,
        min(1.0, lightness + 0.45),
        max(0.0, saturation - 0.35),
    )
    return {
        "main": main_hex,
        "inner": _rgb_to_hex(inner),
        "detail": "#4a5568",
    }


def _resolve_color(raw: str | None, color_map: dict[str, str]) -> str:
    if not raw or raw == "none":
        return "none"
    logical = SVG_COLOR_PLACEHOLDERS.get(raw)
    if logical is not None:
        return color_map[logical]
    return raw


def boat_color(boat: Boat) -> str:
    """Boat colour: type hue modulated by its ``fish / capacity`` ratio."""
    boat_type = getattr(boat, "boat_type", "default") or "default"
    base_hex = TYPE_COLORS.get(boat_type, TYPE_COLORS["default"])

    capacity = getattr(boat, "capacity", 0) or 0
    if capacity <= 0:
        capacity = DEFAULT_MAX_FISH
    ratio = max(0.0, min(1.0, getattr(boat, "fish", 0) / capacity))
    return tint_boat_color(base_hex, ratio)


def _rotate(
    x: float, y: float, cos_t: float, sin_t: float
) -> tuple[float, float]:
    return x * cos_t - y * sin_t, x * sin_t + y * cos_t


def boat_paths(
    boat: Boat,
    *,
    boat_scale: float = 1.0,
) -> list[tuple[MplPath, str, str, float]]:
    """Build the boat paths in grid coordinates.

    Returns ``(path, fill, stroke, linewidth)`` items whose colours may still
    be SVG placeholders.
    """
    position = boat.position
    if position is None:
        return []

    skin_key = boat.size_key
    parsed = _parse_svg_elements(
        RESOURCES_DIR / BOAT_SKINS.get(skin_key, BOAT_SKINS[DEFAULT_SKIN_KEY])
    )
    if parsed is None:
        return []
    drawables, vb_w, vb_h = parsed

    length, beam = BOAT_FOOTPRINTS[skin_key]

    angle = math.radians(DIRECTION_ROTATION_DEG.get(boat.heading, 0.0))
    cos_t, sin_t = math.cos(angle), math.sin(angle)
    centre_x, centre_y = length / 2.0, beam / 2.0

    transformed: list[
        tuple[list[tuple[float, float]], list[int], str, str, float]
    ] = []

    for verts, codes, fill, stroke, linewidth in drawables:
        local_verts: list[tuple[float, float]] = []
        for svg_x, svg_y in verts:
            u = (svg_x / vb_w) * length
            v = (1.0 - svg_y / vb_h) * beam
            local_verts.append(
                _rotate(u - centre_x, v - centre_y, cos_t, sin_t)
            )
        transformed.append((local_verts, codes, fill, stroke, linewidth))

    if not transformed:
        return []

    # The rotated viewBox is the footprint; its margins keep the boat centred.
    rect_corners = [
        _rotate(-centre_x, -centre_y, cos_t, sin_t),
        _rotate(centre_x, -centre_y, cos_t, sin_t),
        _rotate(centre_x, centre_y, cos_t, sin_t),
        _rotate(-centre_x, centre_y, cos_t, sin_t),
    ]
    rect_min_x = min(p[0] for p in rect_corners)
    rect_max_x = max(p[0] for p in rect_corners)
    rect_min_y = min(p[1] for p in rect_corners)
    rect_max_y = max(p[1] for p in rect_corners)

    width = rect_max_x - rect_min_x
    height = rect_max_y - rect_min_y
    if width <= 0 or height <= 0:
        return []

    # Cell ``i`` spans ``[i - 0.5, i + 0.5]``.
    target_x, target_y = position
    left = target_x - 0.5
    bottom = target_y - 0.5

    scale = boat_scale if boat_scale > 0 else 1.0
    centre_grid_x = left + width / 2.0
    centre_grid_y = bottom + height / 2.0

    def to_grid(px: float, py: float) -> tuple[float, float]:
        gx = px - rect_min_x + left
        gy = py - rect_min_y + bottom
        return (
            centre_grid_x + (gx - centre_grid_x) * scale,
            centre_grid_y + (gy - centre_grid_y) * scale,
        )

    paths: list[tuple[MplPath, str, str, float]] = []
    for local_verts, codes, fill, stroke, linewidth in transformed:
        grid_verts = [to_grid(px, py) for px, py in local_verts]
        paths.append((MplPath(grid_verts, codes), fill, stroke, linewidth))
    return paths


def draw_boats(ax, model) -> None:
    """Draw every boat of ``model`` on ``ax``."""
    boats = getattr(model, "boats", None) or []
    if not boats:
        return

    boat_scale = float(getattr(model, "boat_scale", 1.0) or 1.0)

    for boat in boats:
        if boat.position is None:
            continue

        color_map = _color_variants(boat_color(boat))
        for path, fill, stroke, linewidth in boat_paths(
            boat, boat_scale=boat_scale
        ):
            ax.add_patch(
                PathPatch(
                    path,
                    facecolor=_resolve_color(fill, color_map),
                    edgecolor=_resolve_color(stroke, color_map),
                    linewidth=linewidth,
                    zorder=BOAT_ZORDER,
                )
            )
