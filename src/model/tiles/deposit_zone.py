from __future__ import annotations

from typing import TYPE_CHECKING

from mesa import Agent

if TYPE_CHECKING:
    from model.entities.boat import Boat


class DepositZone(Agent):
    def __init__(
        self,
        model,
        cells: tuple[tuple[int, int], ...] = (),
        access_positions: tuple[tuple[int, int], ...] = (),
    ):
        super().__init__(model)
        self.cells = cells
        self.access_positions = access_positions
        self.queue: list[Boat] = []
        self.active_boat: Boat | None = None
        self.is_occupied: bool = False

    def occupy(self, boat: Boat | None = None) -> None:
        """Mark the station busy and refresh its flow field."""
        if boat is not None:
            self.active_boat = boat
        if not self.is_occupied:
            self.is_occupied = True
            if hasattr(self.model, "update_deposit_flow_field"):
                self.model.update_deposit_flow_field()

    def release(self, boat: Boat | None = None) -> None:
        """Free the station and redirect boats toward it."""
        if boat is None or self.active_boat is boat:
            self.active_boat = None
        if self.is_occupied and self.active_boat is None:
            self.is_occupied = False
            if hasattr(self.model, "update_deposit_flow_field"):
                self.model.update_deposit_flow_field()
