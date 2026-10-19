"""Who is asking: the seam between authentication (sessions) and authorisation (visibility).

Every route that reads or changes workspace data takes a `Viewer`. Services filter rows with
`app.auth.visibility` and check rights with the properties below; they never read cookies.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

Role = Literal["admin", "rep"]


@dataclass(frozen=True)
class Viewer:
    workspace_id: uuid.UUID
    user_id: uuid.UUID | None  # user_account id; None for a local process (CLI, MCP, tests)
    app_user_id: uuid.UUID | None  # the viewer's CRM identity in this workspace, if any
    role: Role
    see_all: bool = False
    delete_own: bool = False
    is_superadmin: bool = False

    @property
    def is_admin(self) -> bool:
        return self.is_superadmin or self.role == "admin"

    @property
    def sees_everything(self) -> bool:
        """The admin, or a rep granted *see all* in this workspace."""
        return self.is_admin or self.see_all

    def may_delete(self, owner_app_user_id: uuid.UUID | None) -> bool:
        """The admin always; a rep only with *delete own*, and only what they own."""
        if self.is_admin:
            return True
        return (
            self.delete_own
            and owner_app_user_id is not None
            and owner_app_user_id == self.app_user_id
        )

    @classmethod
    def local_admin(cls, workspace_id: uuid.UUID, app_user_id: uuid.UUID | None = None) -> Viewer:
        """The machine owner: CLI commands, the MCP server, and tests that need no login."""
        return cls(
            workspace_id=workspace_id,
            user_id=None,
            app_user_id=app_user_id,
            role="admin",
            is_superadmin=True,
        )
