from model.model import World
from model.scenario import Scenario
from model.entities.boat import Boat
import solara
from mesa.visualization import SolaraViz, make_space_component
from mesa.visualization.components import PropertyLayerStyle
water_color = "#1f77b4"
fuel_color = "#BFBFBF"
deposit_color = "#8F786D"

def blend_colors(start, end, amount):
    start_rgb = tuple(int(start[index:index + 2], 16) for index in (1, 3, 5))
    end_rgb = tuple(int(end[index:index + 2], 16) for index in (1, 3, 5))
    blended = [
        round(start_value + (end_value - start_value) * amount)
        for start_value, end_value in zip(start_rgb, end_rgb)
    ]
    return "#{:02x}{:02x}{:02x}".format(*blended)


colors = [water_color, "#8fbc8f", fuel_color, deposit_color]
for station_color in (fuel_color, deposit_color):
    for band in range(1, 11):
        colors.append(blend_colors(water_color, station_color, band / 10))

def propertylayer_portrayal(layer):
    if layer.name == "terrain":
        return PropertyLayerStyle(
            colormap=colors,
            alpha=0.8,
            vmin=0,
            vmax=23,
            colorbar=False
        )
    return None

def agent_portrayal(agent):
    if isinstance(agent, Boat):
        fish_ratio = (
            agent.fish / agent.capacity
            if agent.capacity > 0
            else 0
        )
        return {
            "color": blend_colors("#ffffff", "#ff0000", fish_ratio),
            "marker": "o",
            "size": 50 + fish_ratio * 950,
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

def score_component(model):
    solara.Markdown(
        f"## Score : {model.score:.2f}\n\n"
        f"- Prix du poisson : {model.fish_price:.2f}\n"
        f"- Prix du carburant : {model.fuel_price:.2f}\n"
        f"- Poissons déposés : {model.total_fish_deposited}\n"
        f"- Prix remboursé : {model.total_reimbursed_price:.2f}\n"
        f"- Carburant payé : {model.total_fuel_paid:.2f}"
    )


scenario = Scenario(
    ship_spawn_rate=0.1,
    fish_amount=50,
    fish_standard_deviation=5.0,
    fish_price=10.0,
    fuel_price=2.0,
    seed=42,
)

model = World(scenario, demo_boat_fish=20)

page = SolaraViz(
    model,
    components=[score_component, space_component],
    model_params={"scenario": scenario, "demo_boat_fish": 20},
    name="Port Simulation",
)