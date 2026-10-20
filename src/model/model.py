from mesa import Model
from mesa.space import SingleGrid

class World(Model):
    
    def __init__(self, width=10, height=10, torus=True):
        super().__init__()
        self.grid = SingleGrid(width, height, torus)

    def step(self):
        pass