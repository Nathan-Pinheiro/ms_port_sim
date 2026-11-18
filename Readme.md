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

## Run

Double-click `commands\start.bat` to launch the simulation, or
`commands\editor.bat` to edit a port configuration.

Or from the project root:

```bat
solara run src\main.py
python src\port_editor_tk.py
```
