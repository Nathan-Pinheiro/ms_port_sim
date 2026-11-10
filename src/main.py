import solara
from matplotlib.figure import Figure
from mesa.visualization import SolaraViz
from mesa.visualization.components import PropertyLayerStyle
from mesa.visualization.mpl_space_drawing import draw_property_layers
from mesa.visualization.utils import update_counter

from model.entities.boat import Boat
from model.model import World
from model.scenario import Scenario
from model.visualization.boat_portrayal import draw_boats

water_color = "#1f77b4"
deposit_color = "#BFBFBF"
fuel_color = "#8F786D"
entry_exit_color = "#1f77b4"


def blend_colors(start: str, end: str, amount: float) -> str:
    start_rgb = tuple(int(start[i : i + 2], 16) for i in (1, 3, 5))
    end_rgb = tuple(int(end[i : i + 2], 16) for i in (1, 3, 5))
    blended = [
        round(start_val + (end_val - start_val) * amount)
        for start_val, end_val in zip(start_rgb, end_rgb)
    ]
    return "#{:02x}{:02x}{:02x}".format(*blended)


# Ordre des valeurs de terrain : 0=eau, 1=terre, 2=depot, 3=carburant, 4=entree.
colors = [water_color, "#8fbc8f", deposit_color, fuel_color, entry_exit_color]
for station_color in (deposit_color, fuel_color):
    for band in range(1, 11):
        colors.append(blend_colors(water_color, station_color, band / 10))


def propertylayer_portrayal(layer):
    if layer.name == "terrain":
        return PropertyLayerStyle(
            colormap=colors,
            alpha=0.8,
            vmin=0,
            vmax=24,
            colorbar=False,
        )
    return None


@solara.component
def space_component(model):
    """Terrain (property layer) + bateaux vectoriels.

    Les bateaux ne passent volontairement pas par ``make_space_component`` :
    Mesa dessinerait des marqueurs images sans teinte dynamique ni taille en
    cellules. ``draw_boats`` les dessine ici en vectoriel, par-dessus le
    terrain.
    """
    update_counter.get()

    space = model.grid
    fig = Figure()
    ax = fig.add_subplot()

    draw_property_layers(space, propertylayer_portrayal, ax=ax)
    ax.set_xlim(-0.5, space.width - 0.5)
    ax.set_ylim(-0.5, space.height - 0.5)
    ax.set_aspect("equal")

    draw_boats(ax, model)

    solara.FigureMatplotlib(fig, format="png", bbox_inches="tight")


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

# Bateau de demonstration du pathfinding : grand bateau (3x2) qui rejoint le
# depot en suivant le flow field.
test_boat = Boat(
    size=3,
    name="Test Boat Pathfinding",
    speed=1,
    capacity=50,
    fuel_consuption=1,
    fish=30,
)
model.add_boat(test_boat, (1, 1))

page = SolaraViz(
    model,
    components=[score_component, space_component],
    name="Port Simulation - Pathfinding Flow Field",
)
