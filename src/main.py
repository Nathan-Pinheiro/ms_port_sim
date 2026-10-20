from model.model import World
from mesa.visualization import SolaraViz, make_space_component
from matplotlib.colors import ListedColormap
from mesa.visualization.components import PropertyLayerStyle
from mesa import Agent

class DummyAgent(Agent):
    def __init__(self, model):
        super().__init__(model)

from matplotlib.colors import ListedColormap

colors = [
    "#1f77b4",
    "#8fbc8f",
    "#BFBFBF",
    "#8F786D",
]

def propertylayer_portrayal(layer):
    if layer.name == "terrain":
        return PropertyLayerStyle(
            colormap=colors,
            alpha=0.8,
            vmin=0,
            vmax=3,
            colorbar=False
        )
    return None

space_component = make_space_component(
    propertylayer_portrayal=propertylayer_portrayal,
    draw_grid=False,
)

# 1. Instancier le modèle explicitement
model = World(
    ship_spawn_rate=0.1,
    fish_amount=50,
    fish_standard_deviation=5.0,
    seed=42,
)

dummy = DummyAgent(model)
model.grid.place_agent(dummy, (0, 0))

# 2. Passer l'INSTANCE (model), et non la classe (World)
page = SolaraViz(
    model,
    components=[space_component],
    model_params={
        "ship_spawn_rate": {
            "type": "SliderFloat",
            "value": 0.1,
            "label": "Taux d'apparition des navires",
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
        },
        "fish_amount": {
            "type": "SliderInt",
            "value": 50,
            "label": "Nombre de poissons",
            "min": 0,
            "max": 500,
            "step": 1,
        },
        "fish_standard_deviation": {
            "type": "SliderFloat",
            "value": 5.0,
            "label": "Écart-type de dispersion des poissons",
            "min": 0.1,
            "max": 25.0,
            "step": 0.1,
        },
        "seed": {
            "type": "InputText",
            "value": 42,
            "label": "Graine aléatoire",
        },
    },
    name="Port Simulation",
)