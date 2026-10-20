from mesa import Model
from mesa.space import SingleGrid, PropertyLayer

class World(Model):
    
    def __init__(self, width=10, height=10, torus=True):
        super().__init__()
        self.grid = SingleGrid(width, height, torus)
        
        terrain_layer = PropertyLayer(
            "terrain", width, height, default_value=0, dtype=int
        )
        
        self.grid.add_property_layer(terrain_layer)
        
        for x in range(2, 8):
            for y in range(3, 7):
                self.grid.properties["terrain"].set_cell((x, y), 1)
                
    def step(self):
        pass