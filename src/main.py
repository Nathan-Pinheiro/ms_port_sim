import solara
from mesa.visualization import SolaraViz, make_space_component
from mesa.visualization.components import PropertyLayerStyle

from model.entities.boat import Boat
from model.model import World
from model.scenario import Scenario

water_color = "#1f77b4"
deposit_color = "#BFBFBF"  # Blanc/Gris clair pour le DÉCHARGEMENT (Haut)
fuel_color = "#8F786D"     # Marron/Rouge pour le CARBURANT (Bas)


def blend_colors(start: str, end: str, amount: float) -> str:
    start_rgb = tuple(int(start[i : i + 2], 16) for i in (1, 3, 5))
    end_rgb = tuple(int(end[i : i + 2], 16) for i in (1, 3, 5))
    blended = [
        round(start_val + (end_val - start_val) * amount)
        for start_val, end_val in zip(start_rgb, end_rgb)
    ]
    return "#{:02x}{:02x}{:02x}".format(*blended)


# L'ordre est essentiel : deposit_color à l'index 2, fuel_color à l'index 3.
colors = [water_color, "#8fbc8f", deposit_color, fuel_color]

# 1. Génère les accès blancs (dont l'ID 8)
# 2. Génère les accès rouges (dont l'ID 18)
for station_color in (deposit_color, fuel_color):
    for band in range(1, 11):
        colors.append(blend_colors(water_color, station_color, band / 10))


def propertylayer_portrayal(layer):
    if layer.name == "terrain":
        return PropertyLayerStyle(
            colormap=colors,
            alpha=0.8,
            vmin=0,
            vmax=23,
            colorbar=False,
        )
    return None


def agent_portrayal(agent):
    if isinstance(agent, Boat):
        fish_ratio = (
            agent.fish / agent.capacity if agent.capacity > 0 else 0
        )
        return {
            "color": blend_colors("#ffffff", "#ff0000", fish_ratio),
            "marker": "o",
            "size": 100 + fish_ratio * 400,
        }
    return {
        "color": "#000000",
        "marker": "o",
        "size": 50,
    }


space_component = make_space_component(
    agent_portrayal=agent_portrayal,
    propertylayer_portrayal=propertylayer_portrayal,
    draw_grid=False,
)


@solara.component
def score_component(model):
    solara.Markdown(
        f"## Score : {model.score:.2f}\n\n"
        f"- **Prix du poisson** : {model.fish_price:.2f}\n"
        f"- **Prix du carburant** : {model.fuel_price:.2f}\n"
        f"- **Poissons déposés** : {model.total_fish_deposited}\n"
        f"- **Prix remboursé** : {model.total_reimbursed_price:.2f}\n"
        f"- **Carburant payé** : {model.total_fuel_paid:.2f}\n"
        f"- **Bateaux servis** : {model.total_boats_serviced}"
    )


scenario = Scenario(
    ship_spawn_rate=0.1,
    fish_amount=50,
    fish_standard_deviation=5.0,
    fish_price=10.0,
    fuel_price=2.0,
    seed=42,
)

model = World(scenario, demo_boat_fish=None)

spawn_pos = (1, 1)
test_boat = Boat(
    size=3,
    name="Test Boat Pathfinding",
    speed=1,
    capacity=50,
    fuel_consuption=1,
    fish=30,
)
model.add_boat(test_boat, spawn_pos)

page = SolaraViz(
    model,
    components=[score_component, space_component],
    name="Port Simulation - Pathfinding Flow Field",
)