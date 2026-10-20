from model.model import World
from mesa.visualization import SolaraViz, make_space_component
from mesa import Agent

model = World()

class DummyAgent(Agent):
    def __init__(self, model):
        super().__init__(model)

dummy = DummyAgent(model)
model.grid.place_agent(dummy, (0, 0))

space_component = make_space_component()

page = SolaraViz(
    model,
    components=[space_component],
    model_params={}
)