"""전략 Protocol 정의."""

from typing import Protocol

from holdem_core.models.actions import Action
from holdem_core.models.events import ActionRequest


class Strategy(Protocol):
    def decide(self, req: ActionRequest) -> Action: ...
