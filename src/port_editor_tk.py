"""Desktop editor for port configurations.

Run it with ``commands/editor.bat`` or ``python src/port_editor_tk.py``.
Painting writes the JSON file directly, without any web page rerender.

Left-click or drag paints with the selected brush, right-click erases, and
changes are saved to ``data/ports/<map_name>_<port_config_name>.json``.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from model import map_io

AREA_COLORS = {
    map_io.AREA_WATER: "#1f77b4",
    map_io.AREA_EARTH: "#8fbc8f",
    map_io.AREA_ENTRY_EXIT: "#17becf",
}
PORT_COLORS = {
    map_io.PORT_ARTIFICIAL_LAND: "#9e9e6b",
    map_io.PORT_DEPOSIT: "#bfbfbf",
    map_io.PORT_FUEL: "#8f786d",
}
PORT_SYMBOLS = {
    map_io.PORT_EMPTY: "",
    map_io.PORT_ARTIFICIAL_LAND: "L",
    map_io.PORT_DEPOSIT: "D",
    map_io.PORT_FUEL: "F",
}
BRUSHES = [
    ("Empty", map_io.PORT_EMPTY),
    ("Artificial land", map_io.PORT_ARTIFICIAL_LAND),
    ("Deposit", map_io.PORT_DEPOSIT),
    ("Fuel", map_io.PORT_FUEL),
]
LEGEND = [
    ("Water", AREA_COLORS[map_io.AREA_WATER]),
    ("Earth", AREA_COLORS[map_io.AREA_EARTH]),
    ("Entry / exit", AREA_COLORS[map_io.AREA_ENTRY_EXIT]),
    ("Artificial land", PORT_COLORS[map_io.PORT_ARTIFICIAL_LAND]),
    ("Deposit", PORT_COLORS[map_io.PORT_DEPOSIT]),
    ("Fuel", PORT_COLORS[map_io.PORT_FUEL]),
]


class PortEditor:
    CELL = 28

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Port configuration editor")

        self.area: list[list[int]] = []
        self.port: list[list[int]] = []
        self.rect_ids: list[list[int]] = []
        self.text_ids: list[list[int]] = []
        self.brush = map_io.PORT_DEPOSIT
        self.dirty = False
        self.dragging = False

        self.map_var = tk.StringVar()
        self.config_var = tk.StringVar()
        self.new_name_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready.")

        self._build_layout()
        self._load_maps()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_layout(self) -> None:
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        panel = ttk.Frame(self.root, padding=10)
        panel.grid(row=0, column=0, sticky="ns")
        canvas_frame = ttk.Frame(self.root, padding=10)
        canvas_frame.grid(row=0, column=1, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        map_box = ttk.LabelFrame(panel, text="Area map", padding=6)
        map_box.pack(fill="x", pady=(0, 8))
        self.map_combo = ttk.Combobox(
            map_box, textvariable=self.map_var, state="readonly", width=24
        )
        self.map_combo.pack(fill="x")
        self.map_combo.bind("<<ComboboxSelected>>", self._on_map_change)

        config_box = ttk.LabelFrame(panel, text="Port configuration", padding=6)
        config_box.pack(fill="x", pady=(0, 8))
        self.config_combo = ttk.Combobox(
            config_box, textvariable=self.config_var, state="readonly", width=24
        )
        self.config_combo.pack(fill="x")
        self.config_combo.bind("<<ComboboxSelected>>", self._on_config_change)

        new_box = ttk.LabelFrame(panel, text="New configuration", padding=6)
        new_box.pack(fill="x", pady=(0, 8))
        ttk.Label(new_box, text="Name:").pack(anchor="w")
        ttk.Entry(new_box, textvariable=self.new_name_var, width=24).pack(
            fill="x", pady=(2, 4)
        )
        ttk.Button(new_box, text="Create", command=self._create_config).pack(
            fill="x"
        )
        self.new_hint = ttk.Label(new_box, text="", foreground="#555")
        self.new_hint.pack(anchor="w", pady=(4, 0))

        brush_box = ttk.LabelFrame(panel, text="Brush", padding=6)
        brush_box.pack(fill="x", pady=(0, 8))
        self.brush_var = tk.IntVar(value=self.brush)
        for label, value in BRUSHES:
            ttk.Radiobutton(
                brush_box,
                text=label,
                value=value,
                variable=self.brush_var,
                command=self._set_brush_from_var,
            ).pack(anchor="w")

        legend_box = ttk.LabelFrame(panel, text="Legend", padding=6)
        legend_box.pack(fill="x", pady=(0, 8))
        for label, color in LEGEND:
            row = ttk.Frame(legend_box)
            row.pack(fill="x", pady=1)
            swatch = tk.Canvas(
                row, width=14, height=14, highlightthickness=0, bg=color
            )
            swatch.pack(side="left", padx=(0, 6))
            ttk.Label(row, text=label).pack(side="left")

        ttk.Separator(panel).pack(fill="x", pady=8)
        ttk.Label(
            panel,
            text="Left-click / drag: paint\nRight-click / drag: erase",
            foreground="#555",
        ).pack(anchor="w")

        self.canvas = tk.Canvas(
            canvas_frame, bg="#202020", highlightthickness=0
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_right_press)
        self.canvas.bind("<B3-Motion>", self._on_right_drag)
        self.canvas.bind("<ButtonRelease-3>", self._on_release)

        status = ttk.Frame(self.root, padding=(10, 4))
        status.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Label(status, textvariable=self.status_var).pack(anchor="w")

    def _load_maps(self) -> None:
        maps = map_io.list_maps()
        self.map_combo["values"] = maps
        if not maps:
            self.status_var.set(
                f"No map found in {map_io.MAPS_DIR}. Add a JSON map first."
            )
            return
        self.map_var.set(maps[0])
        self._load_map(maps[0])

    def _load_map(self, name: str) -> None:
        try:
            payload = map_io.load_map(name)
        except map_io.MapError as exc:
            messagebox.showerror("Map error", str(exc))
            return
        self.area = [list(row) for row in payload["tiles"]]
        configs = map_io.list_port_configs(name)
        self.config_combo["values"] = configs
        if configs:
            self.config_var.set(configs[0])
            self._load_config(configs[0])
        else:
            self.config_var.set("")
            self.port = map_io.empty_port_tiles(
                len(self.area[0]), len(self.area)
            )
            self._rebuild_canvas()
            self.status_var.set(
                "No configuration yet: create one on the left."
            )
        self._update_new_hint()

    def _load_config(self, name: str) -> None:
        try:
            payload = map_io.load_port_config(self.map_var.get(), name)
        except map_io.MapError as exc:
            messagebox.showerror("Configuration error", str(exc))
            return
        self.port = [list(row) for row in payload["tiles"]]
        self._rebuild_canvas()
        self.dirty = False
        self.status_var.set(
            f"Editing {map_io.port_path(self.map_var.get(), name).name}"
        )

    def _create_config(self) -> None:
        map_name = self.map_var.get()
        if not map_name:
            messagebox.showinfo("No map", "Select an area map first.")
            return
        name = self.new_name_var.get().strip().replace(" ", "_")
        if not name:
            messagebox.showinfo("Name required", "Enter a configuration name.")
            return
        existing = map_io.list_port_configs(map_name)
        if name in existing:
            messagebox.showinfo(
                "Already exists",
                f"{map_name}_{name}.json already exists; select it instead.",
            )
            return
        tiles = map_io.empty_port_tiles(len(self.area[0]), len(self.area))
        try:
            path = map_io.save_port_config(map_name, name, tiles)
        except map_io.MapError as exc:
            messagebox.showerror("Save error", str(exc))
            return
        self.config_combo["values"] = map_io.list_port_configs(map_name)
        self.config_var.set(name)
        self.port = tiles
        self.new_name_var.set("")
        self._rebuild_canvas()
        self._update_new_hint()
        self.status_var.set(f"Created {path.name}")

    def _save(self) -> None:
        map_name = self.map_var.get()
        config_name = self.config_var.get()
        if not map_name or not config_name:
            self.status_var.set(
                "Nothing saved: create or select a configuration first."
            )
            return
        try:
            path = map_io.save_port_config(map_name, config_name, self.port)
        except map_io.MapError as exc:
            messagebox.showerror("Save error", str(exc))
            return
        self.dirty = False
        self.status_var.set(f"Saved {path.name}")

    def _cell_color(self, row: int, column: int) -> str:
        value = self.port[row][column]
        if value in PORT_COLORS:
            return PORT_COLORS[value]
        return AREA_COLORS.get(self.area[row][column], "#cccccc")

    def _rebuild_canvas(self) -> None:
        self.canvas.delete("all")
        self.rect_ids = []
        self.text_ids = []
        if not self.port:
            return
        cell = self.CELL
        height = len(self.port)
        width = len(self.port[0])
        for row in range(height):
            row_rects = []
            row_texts = []
            for column in range(width):
                x0 = column * cell
                y0 = row * cell
                rect = self.canvas.create_rectangle(
                    x0,
                    y0,
                    x0 + cell,
                    y0 + cell,
                    fill=self._cell_color(row, column),
                    outline="#555555",
                )
                text = self.canvas.create_text(
                    x0 + cell / 2,
                    y0 + cell / 2,
                    text=PORT_SYMBOLS.get(self.port[row][column], ""),
                    fill="#111111",
                    font=("Segoe UI", 9, "bold"),
                )
                row_rects.append(rect)
                row_texts.append(text)
            self.rect_ids.append(row_rects)
            self.text_ids.append(row_texts)
        self.canvas.configure(
            width=width * cell + 1, height=height * cell + 1
        )

    def _paint_cell(self, row: int, column: int, value: int) -> None:
        if not self.port:
            return
        if row < 0 or column < 0:
            return
        if row >= len(self.port) or column >= len(self.port[0]):
            return
        if self.port[row][column] == value:
            return
        self.port[row][column] = value
        self.canvas.itemconfig(
            self.rect_ids[row][column], fill=self._cell_color(row, column)
        )
        self.canvas.itemconfig(
            self.text_ids[row][column], text=PORT_SYMBOLS.get(value, "")
        )
        self.dirty = True

    def _event_cell(self, event) -> tuple[int, int] | None:
        if not self.port:
            return None
        column = int(event.x // self.CELL)
        row = int(event.y // self.CELL)
        if 0 <= row < len(self.port) and 0 <= column < len(self.port[0]):
            return row, column
        return None

    def _on_press(self, event) -> None:
        self.dragging = True
        cell = self._event_cell(event)
        if cell:
            self._paint_cell(cell[0], cell[1], self.brush)

    def _on_drag(self, event) -> None:
        if not self.dragging:
            return
        cell = self._event_cell(event)
        if cell:
            self._paint_cell(cell[0], cell[1], self.brush)
            self._maybe_autosave()

    def _on_right_press(self, event) -> None:
        self.dragging = True
        cell = self._event_cell(event)
        if cell:
            self._paint_cell(cell[0], cell[1], map_io.PORT_EMPTY)

    def _on_right_drag(self, event) -> None:
        if not self.dragging:
            return
        cell = self._event_cell(event)
        if cell:
            self._paint_cell(cell[0], cell[1], map_io.PORT_EMPTY)
            self._maybe_autosave()

    def _on_release(self, _event) -> None:
        self.dragging = False
        self._maybe_autosave()

    def _maybe_autosave(self) -> None:
        if self.dirty:
            self._save()

    def _on_map_change(self, _event=None) -> None:
        if self.dirty:
            self._save()
        self._load_map(self.map_var.get())

    def _on_config_change(self, _event=None) -> None:
        if self.dirty:
            self._save()
        name = self.config_var.get()
        if name:
            self._load_config(name)

    def _set_brush_from_var(self) -> None:
        self.brush = self.brush_var.get()

    def _update_new_hint(self) -> None:
        map_name = self.map_var.get()
        if map_name:
            self.new_hint.configure(
                text=f"Saved as {map_name}_<name>.json"
            )

    def _on_close(self) -> None:
        if self.dirty:
            self._save()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    PortEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
