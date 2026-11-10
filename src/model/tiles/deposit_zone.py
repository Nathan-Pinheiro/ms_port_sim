from mesa import Agent


class DepositZone(Agent):
    def __init__(self, model):
        super().__init__(model)
        self.is_occupied: bool = False

    def occupy(self):
        """Marque la station comme occupée et met à jour les chemins."""
        if not self.is_occupied:
            self.is_occupied = True
            if hasattr(self.model, "update_deposit_flow_field"):
                self.model.update_deposit_flow_field()

    def release(self):
        """Libère la station et redirige les bateaux vers celle-ci."""
        if self.is_occupied:
            self.is_occupied = False
            if hasattr(self.model, "update_deposit_flow_field"):
                self.model.update_deposit_flow_field()