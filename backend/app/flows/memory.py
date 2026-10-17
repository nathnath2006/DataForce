"""An in-memory SourceLoader over a dict of DataFrames (tests, and F's unit tests).

Keys: a CRM table name ("deals"), a file id as a string, or a postgres source's table or query.
"""

from __future__ import annotations

import pandas as pd

from app.flows.ports import SourceError
from app.flows.schemas import CrmSource, FileSource, PostgresSource


class MemoryLoader:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def load(self, source: CrmSource | FileSource | PostgresSource, max_rows: int) -> pd.DataFrame:
        if isinstance(source, CrmSource):
            key = source.table
        elif isinstance(source, FileSource):
            key = str(source.file_id)
        else:
            key = source.table or source.query or ""
        df = self.frames.get(key)
        if df is None:
            raise SourceError(f"dataset '{key[:60]}' is not available")
        out = df.head(max_rows).copy()
        if len(df) > max_rows:
            out.attrs["capped"] = True
        return out
