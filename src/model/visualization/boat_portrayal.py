"""Rendu vectoriel des bateaux pour la simulation du port (backend Matplotlib).

Pourquoi ne pas utiliser de marqueurs image ?
---------------------------------------------
Mesa dessine un marqueur fichier (``marker="...png"``) via ``OffsetImage`` et
**ignore completement** la couleur fournie dans ``AgentPortrayalStyle``. La
seule facon de colorer un bateau serait donc de generer un PNG par couleur,
puis un PNG par direction : une explosion combinatoire de fichiers, et une
image par pas de simulation des que le ratio poisson change.

Ce module dessine donc les bateaux directement en vectoriel avec des
``matplotlib.patches.PathPatch``, a partir des SVG de ``resources/boats/`` :

* **aucune image generee** : ni par couleur, ni par direction ;
* la couleur est appliquee a chaque rendu (O(1)), donc le bateau blanchit
  instantanement quand il depose ses poissons ;
* la rotation est un simple changement de repere geometrique ;
* l'empreinte est exacte : le bateau occupe reellement ses cellules.

Reperes et empreinte
--------------------
La position d'un bateau (``boat.pos``) est le **coin bas-gauche** de son
empreinte en cellules. Pour une taille donnee et une orientation donnee,
``Boat.footprint`` renvoie ``(largeur, hauteur)`` :

* taille 1 : 1x1 (toutes orientations) ;
* taille 2 : 2x1 a l'Est/Ouest, 1x2 au Nord/Sud ;
* taille 3 : 3x2 a l'Est/Ouest, 2x3 au Nord/Sud.

Les SVG fournis ont la proue vers la droite (Est). La direction 0 (Nord,
valeur par defaut) applique donc une rotation de +90 degres : le bateau
pointe bien vers le haut.

Taille et ``boat_scale``
------------------------
Comme le dessin se fait en coordonnees de la grille, un bateau occupe toujours
le meme nombre de cellules, quelle que soit la ``scale`` de la carte. Si la
carte grandit, les cellules retirecissent et le bateau parait donc plus petit :
c'est le comportement attendu. ``boat_scale`` (parametre de scenario) ajuste
finement la taille visuelle *dans* l'empreinte, sans jamais dependre de la map.

Configuration
-------------
Toutes les constantes ajustables sont en haut du fichier.
"""

from __future__ import annotations

import colorsys
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath

from mesa.visualization.components import AgentPortrayalStyle

from model.entities.boat import BOAT_FOOTPRINTS, Boat


# ---------------------------------------------------------------------------
# Dossiers
# ---------------------------------------------------------------------------

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources" / "boats"

# ---------------------------------------------------------------------------
# Constantes configurables
# ---------------------------------------------------------------------------

# Ratio de reference quand un bateau n'a pas de capacite renseignee.
DEFAULT_MAX_FISH = 100

# Luminosite utilisee quand le bateau est vide (0 poisson) : quasi blanc.
WHITE_LIGHTNESS = 0.97

# Couleur de base par type de bateau. Seule la teinte (hue) est conservee :
# le ratio poisson/capacite module saturation et luminosite.
TYPE_COLORS: dict[str, str] = {
    "fisher": "#ef0505",     # bleu - pecheur
    "transport": "#ff7f0e",  # orange - transport
    "cargo": "#2ca02c",      # vert - cargo
    "default": "#1f77b4",
}

# Correspondance taille de bateau <-> skin SVG.
# La geometrie (longueur, largeur) vient de ``BOAT_FOOTPRINTS`` dans boat.py,
# afin que le rendu et les deplacements partagent exactement la meme verite.
BOAT_SKINS: dict[int, str] = {
    1: "small_boat.svg",
    2: "medium_boat.svg",
    3: "large_boat.svg",
}
DEFAULT_SKIN_KEY = 1

# Placeholders de couleur dans les fichiers SVG -> nom logique.
SVG_COLOR_PLACEHOLDERS: dict[str, str] = {
    "{color}": "main",
    "{main_color}": "main",
    "{inner_color}": "inner",
    "{detail_color}": "detail",
}

# Rotation (degres, sens anti-horaire) a appliquer au SVG de base (proue Est).
DIRECTION_ROTATION_DEG: dict[int, float] = {
    0: 90.0,   # Nord : la proue passe en haut
    1: 0.0,    # Est  : orientation de base
    2: -90.0,  # Sud  : la proue passe en bas
    3: 180.0,  # Ouest
}

BOAT_ZORDER = 3

# ---------------------------------------------------------------------------
# Cache de parsing SVG (le contenu des fichiers ne change pas a l'execution)
# ---------------------------------------------------------------------------

_SVG_ELEMENTS_CACHE: dict[str, tuple[list[tuple], float, float]] = {}


# ---------------------------------------------------------------------------
# Parsing SVG (path + rect) -> drawables matplotlib
# ---------------------------------------------------------------------------

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


def _rect_to_path(x: float, y: float, w: float, h: float) -> tuple[list[list[float]], list[int]]:
    """Convertit un <rect> en (verts, codes) matplotlib (rx ignore)."""
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
    """Parse un SVG et retourne (drawables, viewbox_w, viewbox_h).

    Un drawable est ``(verts, codes, fill, stroke, stroke_width)`` en
    coordonnees SVG (y vers le bas). Les placeholders de couleur sont conserves
    et resolus au moment du dessin.
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


# ---------------------------------------------------------------------------
# Couleur
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % tuple(
        int(max(0, min(255, round(c * 255)))) for c in rgb
    )


def tint_boat_color(
    base_hex: str,
    fish_ratio: float,
    white_lightness: float = WHITE_LIGHTNESS,
) -> str:
    """Teinte une couleur de base selon le ratio poisson/capacite.

    La teinte (hue) est preservee : seul le couple saturation/luminosite varie.
    A ratio 0 le bateau est quasi blanc, a ratio 1 il reprend sa couleur pleine.
    """
    ratio = max(0.0, min(1.0, fish_ratio))
    r, g, b = _hex_to_rgb(base_hex)
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    new_saturation = saturation * ratio
    new_lightness = white_lightness * (1.0 - ratio) + lightness * ratio
    r2, g2, b2 = colorsys.hls_to_rgb(hue, new_lightness, new_saturation)
    return _rgb_to_hex((r2, g2, b2))


def _color_variants(main_hex: str) -> dict[str, str]:
    """Derive la coque interieure (tres claire) et les details (ardoise)."""
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
    """Resout un placeholder SVG (``{main_color}``) ou une couleur directe."""
    if not raw or raw == "none":
        return "none"
    logical = SVG_COLOR_PLACEHOLDERS.get(raw)
    if logical is not None:
        return color_map[logical]
    return raw


def boat_color(boat: Boat) -> str:
    """Couleur d'un bateau : teinte du type modulee par ``fish / capacity``."""
    boat_type = getattr(boat, "boat_type", "default") or "default"
    base_hex = TYPE_COLORS.get(boat_type, TYPE_COLORS["default"])

    capacity = getattr(boat, "capacity", 0) or 0
    if capacity <= 0:
        capacity = DEFAULT_MAX_FISH
    ratio = max(0.0, min(1.0, getattr(boat, "fish", 0) / capacity))
    return tint_boat_color(base_hex, ratio)


# ---------------------------------------------------------------------------
# Geometrie du bateau -> chemins matplotlib en coordonnees de la grille
# ---------------------------------------------------------------------------

def _rotate(x: float, y: float, cos_t: float, sin_t: float) -> tuple[float, float]:
    return x * cos_t - y * sin_t, x * sin_t + y * cos_t


def boat_paths(
    boat: Boat,
    *,
    boat_scale: float = 1.0,
) -> list[tuple[MplPath, str, str, float]]:
    """Construit les chemins d'un bateau dans le repere de la grille.

    Retourne une liste de ``(path, fill, stroke, linewidth)`` ou ``fill`` et
    ``stroke`` sont encore des couleurs brutes (placeholders non resolus).

    Le bateau est place dans le rectangle de son empreinte, ancree au coin
    bas-gauche de la cellule ``boat.pos`` (qui est donc la cellule bas-gauche
    de l'empreinte).
    """
    position = boat.position
    if position is None:
        return []

    skin_key = boat.size_key
    parsed = _parse_svg_elements(RESOURCES_DIR / BOAT_SKINS.get(skin_key, BOAT_SKINS[DEFAULT_SKIN_KEY]))
    if parsed is None:
        return []
    drawables, vb_w, vb_h = parsed

    # Dimensions de base : longueur (axe proue-poupe, vers +x) et largeur.
    length, beam = BOAT_FOOTPRINTS[skin_key]

    # Passage SVG (y vers le bas) -> repere local (y vers le haut).
    # Puis rotation autour du centre du rectangle de base.
    angle = math.radians(DIRECTION_ROTATION_DEG.get(boat.heading, 0.0))
    cos_t, sin_t = math.cos(angle), math.sin(angle)
    centre_x, centre_y = length / 2.0, beam / 2.0

    transformed: list[tuple[list[tuple[float, float]], list[int], str, str, float]] = []

    for verts, codes, fill, stroke, linewidth in drawables:
        local_verts: list[tuple[float, float]] = []
        for svg_x, svg_y in verts:
            u = (svg_x / vb_w) * length
            v = (1.0 - svg_y / vb_h) * beam
            local_verts.append(_rotate(u - centre_x, v - centre_y, cos_t, sin_t))
        transformed.append((local_verts, codes, fill, stroke, linewidth))

    if not transformed:
        return []

    # Bounding box du viewBox (et non du contenu) apres rotation : c'est lui
    # qui correspond exactement au rectangle d'empreinte. Les marges internes
    # du SVG sont ainsi conservees et le bateau reste centre dans sa case.
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

    # Rectangle cible : cellules occupees (une cellule i occupe [i-0.5, i+0.5]).
    target_x, target_y = position
    left = target_x - 0.5
    bottom = target_y - 0.5

    # Mise a l'echelle autour du centre de l'empreinte (boat_scale).
    scale = boat_scale if boat_scale > 0 else 1.0
    centre_grid_x = left + width / 2.0
    centre_grid_y = bottom + height / 2.0

    def to_grid(px: float, py: float) -> tuple[float, float]:
        # Translation du viewBox tourne sur le coin bas-gauche de l'empreinte.
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


# ---------------------------------------------------------------------------
# Dessin
# ---------------------------------------------------------------------------

def draw_boats(ax, model) -> None:
    """Dessine tous les bateaux du modele sur ``ax``.

    A appeler apres le dessin du terrain (property layer) : les bateaux sont
    ainsi au-dessus de l'eau et des cotes.
    """
    boats = getattr(model, "boats", None) or []
    if not boats:
        return

    boat_scale = float(getattr(model, "boat_scale", 1.0) or 1.0)

    for boat in boats:
        if boat.position is None:
            continue

        color_map = _color_variants(boat_color(boat))
        for path, fill, stroke, linewidth in boat_paths(boat, boat_scale=boat_scale):
            ax.add_patch(
                PathPatch(
                    path,
                    facecolor=_resolve_color(fill, color_map),
                    edgecolor=_resolve_color(stroke, color_map),
                    linewidth=linewidth,
                    zorder=BOAT_ZORDER,
                )
            )


# ---------------------------------------------------------------------------
# Compatibilite Mesa
# ---------------------------------------------------------------------------

def agent_portrayal(agent: Any) -> AgentPortrayalStyle:
    """Portrayal pour les agents non-bateaux.

    Les bateaux sont dessines par :func:`draw_boats` (vectoriel, empreinte
    exacte). S'ils passaient par Mesa, ils seraient dessines comme de simples
    marqueurs images, sans possibilite de teinte dynamique ni de taille en
    cellules. On retourne donc un style invisible pour eux afin de ne pas les
    dessiner deux fois si ``make_space_component`` est utilise par ailleurs.
    """
    if isinstance(agent, Boat):
        return AgentPortrayalStyle(
            size=0,
            marker="o",
            color=(0.0, 0.0, 0.0, 0.0),
            edgecolors=(0.0, 0.0, 0.0, 0.0),
            linewidths=0,
            alpha=0.0,
            zorder=0,
        )

    return AgentPortrayalStyle(
        color="#000000",
        marker="o",
        size=50,
        zorder=1,
        alpha=1.0,
    )
