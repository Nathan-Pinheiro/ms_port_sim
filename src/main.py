from __future__ import annotations

import solara
from matplotlib.figure import Figure
from mesa.visualization.components import PropertyLayerStyle
from mesa.visualization.mpl_space_drawing import draw_property_layers
from mesa.visualization.solara_viz import ModelController, ShowSteps
from mesa.visualization.utils import update_counter

from model import map_io
from model.arrival_profiles import (
    DEFAULT_PORT_TYPE,
    PORT_TYPE_LABELS,
)
from model.model import World
from model.scenario import Scenario
from model.visualization.boat_portrayal import draw_boats

water_color = "#1f77b4"
earth_color = "#8fbc8f"
artificial_land_color = "#9e9e6b"
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


# Indexed by terrain value: 0 water, 1 earth, 2 deposit, 3 fuel, 4 entry/exit,
# 5 artificial land, 8 deposit access and 18 fuel access.
colors = [
    water_color,
    earth_color,
    deposit_color,
    fuel_color,
    entry_exit_color,
    artificial_land_color,
    water_color,
    water_color,
    blend_colors(water_color, deposit_color, 0.45),
]
colors += [water_color] * 9
colors.append(blend_colors(water_color, fuel_color, 0.45))
colors += [water_color] * 6

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
        # vmin > 0 keeps NaN cells (land and stations) transparent.
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
    """Terrain, then vector boats on top of it."""
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


def _revenue_time_ticks(
    start_hour: int,
    duration_hours: int,
) -> tuple[list[int], list[str]]:
    offsets = list(range(0, duration_hours + 1, 2))
    if offsets[-1] != duration_hours:
        offsets.append(duration_hours)
    labels = [f"{(start_hour + offset) % 24:02d}:00" for offset in offsets]
    return offsets, labels


@solara.component
def revenue_curve_component(model):
    """Line chart of the money earned during each 30-minute interval."""
    update_counter.get()

    values = model.revenue_per_interval
    fig = Figure(figsize=(3.6, 2.6))
    ax = fig.add_subplot()

    if values:
        interval_hours = model.REVENUE_INTERVAL_MINUTES / 60
        xs = [
            interval_hours * index
            for index in range(1, len(values) + 1)
        ]
        ax.plot(xs, values, marker="o", color="#1f77b4", linewidth=1.5)
        ticks, labels = _revenue_time_ticks(
            model.SIMULATION_START_HOUR,
            model.SIMULATION_HOURS,
        )
        ax.set_xlim(0, model.SIMULATION_HOURS)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
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
        "| Item | Count | Unit | Total |\n"
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
        "| Product | Qty sold | Unit price | Revenue |\n"
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


def build_model(scenario: Scenario) -> World:
    """Create a new, empty port simulation."""
    return World(scenario)


def make_scenario(
    map_name: str,
    config_name: str,
    port_type: str = DEFAULT_PORT_TYPE,
) -> Scenario:
    return Scenario(
        map_name=map_name,
        port_config_name=config_name,
        port_type=port_type,
        fish_amount=50,
        fish_standard_deviation=5.0,
        fish_price=5.0,
        fuel_price=1.5,
        seed=42,
    )


_available_maps = map_io.list_maps()
_initial_map = _available_maps[0] if _available_maps else "matosinhos"
_available_configs = map_io.list_port_configs(_initial_map)
_initial_config = _available_configs[0] if _available_configs else "default"
initial_scenario = make_scenario(_initial_map, _initial_config)
initial_model = build_model(initial_scenario)


@solara.component
def Page():
    model = solara.use_reactive(initial_model)
    model_parameters = solara.use_reactive({"scenario": initial_scenario})
    play_interval = solara.use_reactive(100)
    render_interval = solara.use_reactive(1)
    use_threads = solara.use_reactive(False)

    maps = map_io.list_maps()
    selected_map = solara.use_reactive(model.value.map_name)
    selected_config = solara.use_reactive(model.value.port_config_name)
    selected_port_type = solara.use_reactive(model.value.port_type)
    configs = map_io.list_port_configs(selected_map.value)
    port_message = solara.use_reactive("")

    def on_map_change(name: str) -> None:
        selected_map.set(name)
        available = map_io.list_port_configs(name)
        selected_config.set(available[0] if available else "")

    def on_port_type_change(label: str) -> None:
        selected_port_type.set(
            next(
                key for key, value in PORT_TYPE_LABELS.items()
                if value == label
            )
        )

    def load_selected() -> None:
        if not selected_map.value or not selected_config.value:
            port_message.set("Choose a map and a port configuration first.")
            return
        scenario = make_scenario(
            selected_map.value,
            selected_config.value,
            selected_port_type.value,
        )
        try:
            new_model = build_model(scenario)
        except (map_io.MapError, ValueError) as exc:
            port_message.set(str(exc))
            return
        model_parameters.set({"scenario": scenario})
        model.set(new_model)
        port_message.set(
            f"Loaded {selected_map.value} / {selected_config.value}"
        )

    with solara.AppBar():
        solara.AppBarTitle("Port Simulation")
        solara.lab.ThemeToggle()

    # Everything except the map lives in the left sidebar.
    with solara.Sidebar(), solara.Column(
        style={"width": "310px", "overflowX": "auto"}
    ):
        with solara.Card("Port"):
            solara.Select(
                label="Area map",
                values=maps,
                value=selected_map.value,
                on_value=on_map_change,
            )
            solara.Select(
                label="Port configuration",
                values=configs,
                value=(
                    selected_config.value
                    if selected_config.value in configs
                    else None
                ),
                on_value=selected_config.set,
            )
            solara.Select(
                label="Port type",
                values=list(PORT_TYPE_LABELS.values()),
                value=PORT_TYPE_LABELS[selected_port_type.value],
                on_value=on_port_type_change,
            )
            solara.Button("Load map / configuration", on_click=load_selected)
            solara.Markdown(
                f"**Loaded:** {model.value.map_name} / "
                f"{model.value.port_config_name} — "
                f"{PORT_TYPE_LABELS[model.value.port_type]}"
            )
            if port_message.value:
                solara.Markdown(f"_{port_message.value}_")
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
                "width": "250px",
                "flexShrink": "0",
                "padding": "8px",
            }
        ):
            time_component(model.value)
            solara.Markdown("#### Revenue per 30 min")
            revenue_curve_component(model.value)


page = Page