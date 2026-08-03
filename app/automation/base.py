from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SubmissionResult:
    success: bool
    actual_url: str | None = None
    message: str = ""


class ChannelAdapter(ABC):
    @abstractmethod
    async def submit_link(
        self,
        target_url: str,
        anchor_text: str,
        credentials: dict[str, Any],
        config: dict[str, Any],
    ) -> SubmissionResult:
        """Submit one backlink and return the published URL when successful."""

