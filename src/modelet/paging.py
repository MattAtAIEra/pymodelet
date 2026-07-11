"""Paging value objects, mirroring modelet.model.paging."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PagingElement:
    target_page: int = 1
    rows_per_page: int = 10


@dataclass
class PageContainer:
    rows: list = field(default_factory=list)
    total_pages: int = 0
    total_records: int = 0

    def generate_page_numbers(self) -> list[str]:
        return [str(n) for n in range(1, self.total_pages + 1)]
