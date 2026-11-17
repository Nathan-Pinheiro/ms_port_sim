import solara
from matplotlib.figure import Figure
from mesa.visualization.components import PropertyLayerStyle
from mesa.visualization.mpl_space_drawing import draw_property_layers
from mesa.visualization.solara_viz import ModelController, ShowSteps
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

colors = [water_color, "#8fbc8f", deposit_color, fuel_color, entry_exit_color]
for station_color in (deposit_color, fuel_color):
    for band in range(1, 11):
        colors.append(blend_colors(water_color, station_color, band / 10))

agitation_colors = ["#1f77b4", "#0B66AC"]

def propertylayer_portrayal(layer):
    if layer.name == "terrain":
        return PropertyLayerStyle(
            colormap=colors,
            alpha=0.8,
            vmin=0,
            vmax=24,
            colorbar=False,
        )
    if layer.name == "agitation":
        # Calm = shallow-sea blue, rough = very dark blue.
        # vmin > 0 is intentional: non-navigable cells are NaN and must stay
        # transparent (otherwise Mesa computes np.min(data) = NaN).
        return PropertyLayerStyle(
            colormap=agitation_colors,
            alpha=0.85,
            vmin=0.001,
            vmax=1.0,
            colorbar=False,
        )
    return None


@solara.component
def space_component(model):
    """Terrain (property layer) + vector boats.

    Boats intentionally bypass ``make_space_component``: Mesa would draw them
    as image markers without dynamic tint or cell-sized footprints.
    ``draw_boats`` renders them here as vectors on top of the terrain.
    """
    update_counter.get()

    space = model.grid
    fig = Figure(figsize=(9, 9))
    ax = fig.add_subplot()

    draw_property_layers(space, propertylayer_portrayal, ax=ax)
    ax.set_xlim(-0.5, space.width - 0.5)
    ax.set_ylim(-0.5, space.height - 0.5)
    ax.set_aspect("equal")

    draw_boats(ax, model)

    solara.FigureMatplotlib(fig, format="png", bbox_inches="tight")


@solara.component
def time_component(model):
    update_counter.get()
    solara.Markdown(f"**Simulated time:** {model.simulation_time}")


@solara.component
def revenue_curve_component(model):
    """Line chart of the money earned during each 30-minute interval."""
    update_counter.get()

    values = model.revenue_per_interval
    fig = Figure(figsize=(4.2, 2.8))
    ax = fig.add_subplot()

    if values:
        xs = list(range(1, len(values) + 1))
        ax.plot(xs, values, marker="o", color="#1f77b4", linewidth=1.5)
        labels = []
        for index in range(len(values)):
            minutes = (index + 1) * model.REVENUE_INTERVAL_MINUTES
            labels.append(f"{minutes // 60}:{minutes % 60:02d}")
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=45, fontsize=7)
        ax.set_ylabel("Revenue (€)")
        ax.grid(True, alpha=0.3)
    else:
        ax.text(
            0.5,
            0.5,
            "Waiting for the first\n30-minute interval",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=9,
        )
        ax.set_xticks([])
        ax.set_yticks([])

    solara.FigureMatplotlib(fig, format="png", bbox_inches="tight")


def _format_days(days: float | None) -> str:
    return "—" if days is None else f"{days:,.1f} days"


@solara.component
def estimates_component(model):
    """Revenue estimates and estimated time to break even."""
    update_counter.get()

    def percent_of_cost(value: float) -> str:
        if model.total_cost <= 0:
            return "—"
        percent = value / model.total_cost * 100
        if percent <= 0:
            return "0.00% of the port cost"
        if percent < 0.01:
            return f"{percent:.5f}% of the port cost"
        if percent < 1:
            return f"{percent:.3f}% of the port cost"
        return f"{percent:,.2f}% of the port cost"

    with solara.Card("Estimations"):
        solara.Markdown(
            "**Estimated revenues:**\n\n"
            f"- {model.revenue_per_hour:,.2f} €/h "
            f"({percent_of_cost(model.revenue_per_hour)})\n"
            f"- {model.estimated_daily_revenue:,.2f} €/day "
            f"({percent_of_cost(model.estimated_daily_revenue)})\n"
            f"- {model.estimated_annual_revenue:,.2f} €/year "
            f"({percent_of_cost(model.estimated_annual_revenue)})\n\n"
            "**Estimated days to break even the port:** "
            f"{_format_days(model.estimated_break_even_days)}"
        )


@solara.component
def costs_component(model):
    """Fixed prices of the paid tiles."""
    update_counter.get()
    solara.Markdown(
        "| Item | Count | Unit price | Total |\n"
        "|---|---:|---:|---:|\n"
        f"| Fuel station | {model.fuel_station_count} | "
        f"{model.fuel_station_construction_cost:,} € | "
        f"{model.fuel_station_total_cost:,} € |\n"
        f"| Deposit station | {model.deposit_station_count} | "
        f"{model.deposit_station_construction_cost:,} € | "
        f"{model.deposit_station_total_cost:,} € |\n"
        f"| **Port total** | — | — | **{model.total_cost:,} €** |"
    )


@solara.component
def revenues_component(model):
    """Revenue detail by product, based on unit prices."""
    update_counter.get()
    solara.Markdown(
        "| Product | Quantity sold | Unit price | Total revenue |\n"
        "|---|---:|---:|---:|\n"
        f"| Fuel | {model.total_fuel_refilled:.2f} | "
        f"{model.fuel_price:.2f} € | {model.fuel_station_revenue:.2f} € |\n"
        f"| Fish | {model.total_fish_deposited} | "
        f"{model.fish_price:.2f} € | {model.deposit_revenue:.2f} € |\n"
        f"| **Total** | — | — | **{model.total_revenue:.2f} €** |"
    )


@solara.component
def prices_component(model):
    """Collapsible costs and revenues sections."""
    update_counter.get()
    with solara.Card("Prices"):
        with solara.Details(summary="Costs", expand=True):
            costs_component(model)
        with solara.Details(summary="Revenues", expand=True):
            revenues_component(model)


scenario = Scenario(
    ship_spawn_rate=0.1,
    fish_amount=50,
    fish_standard_deviation=5.0,
    fish_price=10.0,
    fuel_price=2.0,
    seed=42,
)

initial_model = World(scenario, demo_boat_fish=None)

# Pathfinding demo boat: large boat (3x2) that reaches the deposit station by
# following the flow field.
test_boat = Boat(
    size=3,
    name="Test Boat Pathfinding",
    speed=1,
    capacity=50,
    fuel_consuption=1,
    fish=30,
)
initial_model.add_boat(test_boat, (1, 1))


@solara.component
def Page():
    model = solara.use_reactive(initial_model)
    model_parameters = solara.use_reactive({})
    play_interval = solara.use_reactive(100)
    render_interval = solara.use_reactive(1)
    use_threads = solara.use_reactive(False)

    with solara.AppBar():
        solara.AppBarTitle("Port Simulation")
        solara.lab.ThemeToggle()

    # Everything except the map lives in the left sidebar.
    with solara.Sidebar(), solara.Column():
        with solara.Card("Controls"):
            solara.SliderInt(
                label="Play Interval (ms)",
                value=play_interval,
                on_value=play_interval.set,
                min=1,
                max=500,
                step=10,
            )
            solara.SliderInt(
                label="Render Interval (steps)",
                value=render_interval,
                on_value=render_interval.set,
                min=1,
                max=100,
                step=2,
            )
            solara.Checkbox(
                label="Use Threads",
                value=use_threads,
                on_value=use_threads.set,
            )
            ModelController(
                model,
                model_parameters=model_parameters,
                play_interval=play_interval,
                render_interval=render_interval,
                use_threads=use_threads,
            )
        estimates_component(model.value)
        prices_component(model.value)
        # Information stays at the bottom of the sidebar.
        with solara.Card("Information"):
            ShowSteps(model.value)

    # Map area: map on the left, time and revenue curve on the right.
    with solara.Row(
        style={
            "width": "100%",
            "alignItems": "flex-start",
            "flexWrap": "nowrap",
        }
    ):
        with solara.Column(style={"flex": "1", "minWidth": "0"}):
            space_component(model.value)
        with solara.Column(
            style={
                "width": "360px",
                "flexShrink": "0",
                "padding": "8px",
            }
        ):
            time_component(model.value)
            solara.Markdown("#### Revenue per 30 min")
            revenue_curve_component(model.value)


page = Page