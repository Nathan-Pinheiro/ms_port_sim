# Port simulation

## Layout

- `data/maps/` — area maps (`0` water, `1` earth, `2` entry/exit).
- `data/ports/` — port configurations (`0` empty, `5` artificial land,
  `6` deposit, `7` fuel). Files are named `<map_name>_<port_config_name>.json`
  and each configuration references its map.
- `commands/` — launcher scripts.
- `src/main.py` — the simulation dashboard.
- `src/port_editor_tk.py` — the desktop port-configuration editor.

At start-up the model fuses the selected area map with the selected port
configuration, then builds the terrain grid.

## Port types and arrivals

Choose a port profile in the simulation sidebar:

- Local shelter: 5–15 small, 0–3 medium and 0 large boats per day.
- Regional port: 15–40 small, 5–15 medium and 1–4 large boats per day.
- Structured fishing port: 30–80 small, 15–35 medium and 4–12 large boats
  per day.

The simulator samples each vessel class's daily count within its range and
randomizes arrival times around morning and late-day landing peaks. The
simulation day runs from 07:00 to 21:00, preserving the selected profile's
daily arrival count within that shorter active period. Arrivals wait if the
entrance is temporarily blocked.

## Run

Double-click `commands\start.bat` to launch the simulation, or
`commands\editor.bat` to edit a port configuration.

Or from the project root:

```bat
solara run src\main.py
python src\port_editor_tk.py
```
