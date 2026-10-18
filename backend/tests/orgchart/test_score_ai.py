"""The eval scorer's --ai option: clear refusal without saved AI settings (test DB only)."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

from app.services import llm_settings

pytestmark = pytest.mark.integration

SCORE = pathlib.Path(__file__).resolve().parents[2] / "eval" / "meetings" / "score.py"


def load():
    spec = importlib.util.spec_from_file_location("score_under_test", SCORE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ai_without_settings_exits_non_zero_with_a_message(
    db_session, session_factory, ws_id, monkeypatch, capsys
):
    import app.cli._common as common

    monkeypatch.setattr(common, "session_factory", lambda: session_factory)
    from sqlalchemy import select

    from app.db.models import Workspace

    slug = db_session.scalar(select(Workspace.slug).where(Workspace.id == ws_id))
    with pytest.raises(SystemExit) as exc:
        load().open_ai(slug)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "AI model saved in Settings" in err


def test_ai_with_settings_builds_a_pass_and_never_prints_the_key(
    db_session, session_factory, ws_id, monkeypatch, capsys
):
    from sqlalchemy import select

    import app.cli._common as common
    from app.config import get_settings
    from app.db.models import Workspace

    key = "AIzaSyTESTKEY-0123456789abcdefghij"
    llm_settings.save_settings(
        db_session,
        ws_id,
        provider="gemini",
        model="gemini-2.5-flash",
        api_key=key,
        settings=get_settings(),
    )
    monkeypatch.setattr(common, "session_factory", lambda: session_factory)
    slug = db_session.scalar(select(Workspace.slug).where(Workspace.id == ws_id))
    session, ai_pass = load().open_ai(slug)
    assert ai_pass.provider_name == "gemini"
    out = capsys.readouterr()
    assert key not in out.out + out.err and "gemini-2.5-flash" in out.out
    session.close()
