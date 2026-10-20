from model.model import World
from mesa.visualization import SolaraViz, make_space_component
from matplotlib.colors import ListedColormap
from mesa.visualization.components import PropertyLayerStyle
from mesa import Agent

model = World()

class DummyAgent(Agent):
    def __init__(self, model):
        super().__init__(model)

dummy = DummyAgent(model)
model.grid.place_agent(dummy, (0, 0))

def propertylayer_portrayal(layer):
    if layer.name == "terrain":
        return PropertyLayerStyle(
            colormap="viridis",
            alpha=0.8,
            colorbar=True
        )
    return None

space_component = make_space_component(
    propertylayer_portrayal=propertylayer_portrayal
)

page = SolaraViz(
    model,
    components=[space_component],
    model_params={}
)