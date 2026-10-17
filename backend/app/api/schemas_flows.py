"""Request / response models of the flow, file and connection routes (agent F)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from app.flows.schemas import ColumnInfo, FlowGraph

# No control characters (NUL makes Postgres fail), no surrounding blanks.
Name = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\x00-\x1f\x7f]+$"
    ),
]
Description = Annotated[
    str, StringConstraints(max_length=2000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$")
]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- flows ----------------------------------------------------------------------------------------
class FlowCreate(_In):
    name: Name
    description: Description | None = None
    graph: FlowGraph = Field(default_factory=FlowGraph)


class FlowUpdate(_In):
    name: Name | None = None
    description: Description | None = None
    graph: FlowGraph | None = None


class FlowSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    n_nodes: int
    updated_at: datetime


class FlowOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    graph: FlowGraph
    created_at: datetime
    updated_at: datetime


class BlockPorts(BaseModel):
    inputs: list[str]
    outputs: list[str]


class Catalog(BaseModel):
    blocks: dict[str, BlockPorts]
    crm_tables: dict[str, list[ColumnInfo]]


# --- files ----------------------------------------------------------------------------------------
class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    size_bytes: int
    media_type: str
    sheet: str | None
    n_rows: int | None
    columns: list[ColumnInfo]
    created_at: datetime


# --- connections ----------------------------------------------------------------------------------
HOST = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, pattern=r"^[A-Za-z0-9:\[][A-Za-z0-9._:\-\[\]]{0,252}$"
    ),
]
SslMode = Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]
Ident = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[^\x00-\x1f\x7f]+$"
    ),
]


class ConnectionIn(_In):
    name: Name
    host: HOST
    port: int = Field(default=5432, ge=1, le=65535)
    database: Ident
    username: Ident
    password: SecretStr | None = Field(default=None, max_length=1000)
    sslmode: SslMode = "require"


class ConnectionPatch(_In):
    name: Name | None = None
    host: HOST | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    database: Ident | None = None
    username: Ident | None = None
    password: SecretStr | None = Field(default=None, max_length=1000)  # empty keeps the stored one
    sslmode: SslMode | None = None


class ConnectionOut(BaseModel):
    """Never carries the password (nor whether it is sealed beyond `has_password`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    host: str
    port: int
    database: str
    username: str
    sslmode: str
    has_password: bool
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_error: str | None
    created_at: datetime


class TableRef(BaseModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    name: str

    model_config = ConfigDict(populate_by_name=True)
