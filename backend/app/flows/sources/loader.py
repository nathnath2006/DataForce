"""DB-backed `SourceLoader`: every load opens its own short-lived session, so the engine can run
in a worker thread and no session outlives the request."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import DataConnection, UploadedFile
from app.flows.ports import SourceError
from app.flows.schemas import CrmSource, FileSource, PostgresSource
from app.flows.sources import files as parsing
from app.flows.sources import postgres
from app.flows.sources.crm import load_crm_table

log = logging.getLogger(__name__)


class DbSourceLoader:
    def __init__(
        self, session_factory: Callable[[], Session], ws_id: uuid.UUID, settings: Settings
    ) -> None:
        self._factory = session_factory
        self._ws_id = ws_id
        self._settings = settings

    def load(self, source: CrmSource | FileSource | PostgresSource, max_rows: int) -> pd.DataFrame:
        try:
            if isinstance(source, CrmSource):
                return self._crm(source, max_rows)
            if isinstance(source, FileSource):
                return self._file(source, max_rows)
            return self._postgres(source, max_rows)
        except SourceError:
            raise
        except SQLAlchemyError as exc:
            log.error("source read failed: %s", type(exc).__name__)
            raise SourceError("the data could not be read from the database") from None

    def _crm(self, source: CrmSource, max_rows: int) -> pd.DataFrame:
        session = self._factory()
        try:
            return load_crm_table(session, self._ws_id, source.table, max_rows)
        finally:
            session.close()

    def _file(self, source: FileSource, max_rows: int) -> pd.DataFrame:
        session = self._factory()
        try:
            row = session.get(UploadedFile, source.file_id)
            if row is None or row.workspace_id != self._ws_id:
                raise SourceError("the uploaded file no longer exists")
            name, data, sheet = row.name, bytes(row.content), row.sheet
        finally:
            session.close()
        try:
            parsed = parsing.parse_file(
                name,
                data,
                cap_bytes=self._settings.upload_max_bytes,
                max_rows=max_rows,
                sheet=sheet,
            )
        except parsing.UploadRefused as exc:
            raise SourceError(str(exc)) from None
        return parsed.frame

    def _postgres(self, source: PostgresSource, max_rows: int) -> pd.DataFrame:
        from app.services.data_connections import target_of  # avoid an import cycle at load

        session = self._factory()
        try:
            row = session.get(DataConnection, source.connection_id)
            if row is None or row.workspace_id != self._ws_id:
                raise SourceError("the database connection no longer exists")
            postgres.refuse_app_database(row.host, row.port, row.database)
            target = target_of(row, self._settings)
        finally:
            session.close()
        if source.table is not None:
            return postgres.load_table(target, source.table, max_rows)
        assert source.query is not None
        return postgres.load_query(target, source.query, max_rows)
