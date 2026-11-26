from __future__ import annotations

from mesa import Agent


class DepositZone(Agent):
    """One deposit tile and the water cells that can serve it."""

    def __init__(
        self,
        model,
        cell: tuple[int, int],
        access_positions: tuple[tuple[int, int], ...] = (),
    ):
        super().__init__(model)
        self.cell = cell
        self.access_positions = access_positions
