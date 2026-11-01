from model.model import World
from model.scenario import Scenario
from mesa.visualization import SolaraViz, make_space_component
from mesa.visualization.components import PropertyLayerStyle
from mesa import Agent

class DummyAgent(Agent):
    def __init__(self, model):
        super().__init__(model)

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

space_component = make_space_component(
    propertylayer_portrayal=propertylayer_portrayal,
    draw_grid=False,
)

model = World(
    Scenario(
        ship_spawn_rate=0.1,
        fish_amount=50,
        fish_standard_deviation=5.0,
        seed=42,
    )
)

dummy = DummyAgent(model)
model.grid.place_agent(dummy, (0, 0))

page = SolaraViz(
    model,
    components=[space_component],
    name="Port Simulation",
)