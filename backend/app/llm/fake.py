"""Offline, deterministic stand-ins for the LLM and the embedder.

* `FakeLLM` is generic: for any pydantic schema it builds a deterministic, schema-valid instance
  (enums take their first member, strings a stable hash-based token, numbers small constants,
  lists one item or none, optionals None). `register(schema, handler)` overrides a specific schema
  (M2: title classification, theme naming). Its output carries no real signal.
* `FakeEmbedder` is a signed hashing-trick bag of words (blake2b, stable across processes),
  L2-normalized: texts about the same things have a higher cosine.

They are heuristics, not intelligence: do not read quality conclusions out of numbers produced
with them.
"""

from __future__ import annotations

import enum
import hashlib
import math
import re
import types
import typing
import unicodedata
from collections import Counter
from collections.abc import Callable
from typing import Any, Literal, TypeVar, get_args, get_origin

import numpy as np
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from app.domain.ports import ChatMessage, TextResult, UsageRecorder
from app.llm.errors import LLMError
from app.llm.usage import CallTimer

T = TypeVar("T", bound=BaseModel)

_MAX_DEPTH = 6


def fold(text: str) -> str:
    """Lowercase + strip accents, keeping the exact length so indexes map back to `text`."""
    out: list[str] = []
    for ch in text:
        base = unicodedata.normalize("NFD", ch)[0]
        low = base.lower()
        out.append(low if len(low) == 1 else base)
    return "".join(out)


def _compile(terms: list[str]) -> re.Pattern[str]:
    """Word-start match; a trailing '$' in a term means whole word."""
    parts = [re.escape(t[:-1]) + r"\b" if t.endswith("$") else re.escape(t) for t in terms]
    return re.compile(r"\b(?:" + "|".join(parts) + ")")


def _token(path: str) -> str:
    return "fake-" + hashlib.blake2b(path.encode("utf-8"), digest_size=4).hexdigest()


def _build(tp: Any, path: str, depth: int) -> Any:
    origin = get_origin(tp)
    args = get_args(tp)
    if tp is Any:
        return _token(path)
    if origin is typing.Annotated:
        return _build(args[0], path, depth)
    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) < len(args):
            return None
        return _build(non_none[0], path, depth)
    if origin is Literal:
        return args[0]
    if origin in (list, set, frozenset, tuple) or tp in (list, set, tuple):
        if depth >= _MAX_DEPTH or not args:
            return []
        if origin is tuple and not (len(args) == 2 and args[1] is Ellipsis):
            return tuple(_build(a, f"{path}.{i}", depth + 1) for i, a in enumerate(args))
        item = _build(args[0], f"{path}[0]", depth + 1)
        return {"list": [item], "set": [item]}.get(origin.__name__ if origin else "list", [item])
    if origin is dict or tp is dict:
        return {}
    if isinstance(tp, type):
        if issubclass(tp, enum.Enum):
            return next(iter(tp))
        if issubclass(tp, BaseModel):
            return _instance(tp, path, depth + 1)
        if tp is bool:
            return False
        if tp is int:
            return 1
        if tp is float:
            return 0.5
        if tp is str:
            return _token(path)
    return _token(path)


def _instance(schema: type[BaseModel], path: str, depth: int) -> BaseModel:
    data: dict[str, Any] = {}
    for name, field in schema.model_fields.items():
        if field.default is not PydanticUndefined or field.default_factory is not None:
            continue  # the model's own default applies
        data[name] = _build(field.annotation, f"{path}.{name}", depth)
    return schema.model_validate(data)


def build_fake[M: BaseModel](schema: type[M]) -> M:
    """A deterministic schema-valid instance (constraints such as min_length are validated)."""
    try:
        return schema.model_validate(_instance(schema, schema.__name__, 0).model_dump())  # type: ignore[return-value]
    except Exception as exc:
        raise LLMError(f"fake: cannot build {schema.__name__} ({type(exc).__name__})") from None


Handler = Callable[[str, str], BaseModel | dict[str, Any]]


class FakeLLM:
    """Deterministic `LLMProvider` for any pydantic schema; `register` adds specific handlers."""

    name = "fake"
    model = "fake-generic-v1"

    def __init__(self, usage: UsageRecorder | None = None) -> None:
        self._usage = usage
        self._handlers: dict[type[BaseModel], Handler] = {}
        self._text_handler: Callable[[str, list[ChatMessage]], str] | None = None
        self.text_calls: list[tuple[str, list[ChatMessage]]] = []

    def register(self, schema: type[T], handler: Callable[[str, str], T | dict[str, Any]]) -> None:
        """`handler(system, user)` returns an instance (or dict) used for `schema`."""
        self._handlers[schema] = handler

    def register_text(self, handler: Callable[[str, list[ChatMessage]], str]) -> None:
        """`handler(system, messages)` returns the reply of `generate_text`."""
        self._text_handler = handler

    async def generate_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        purpose: Literal["assistant", "connection_test"],
        max_output_tokens: int = 800,
    ) -> TextResult:
        timer = CallTimer(self._usage, provider=self.name, model=self.model, purpose=purpose)
        self.text_calls.append((system, list(messages)))
        try:
            if self._text_handler is not None:
                text = self._text_handler(system, messages)
            elif purpose == "connection_test":
                text = "OK"
            else:
                text = "Fake answer: see the facts."
        except LLMError as exc:
            timer.failure(str(exc))
            raise
        n_in = (len(system) + sum(len(m.content) for m in messages)) // 4
        n_out = len(text) // 4
        timer.success(input_tokens=n_in, output_tokens=n_out)
        return TextResult(text=text, input_tokens=n_in, output_tokens=n_out)

    async def generate_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        purpose: Literal["title_classification", "theme_naming", "explanation"],
        max_output_tokens: int = 4096,
    ) -> T:
        timer = CallTimer(self._usage, provider=self.name, model=self.model, purpose=purpose)
        try:
            handler = self._handlers.get(schema)
            if handler is None:
                result: BaseModel = build_fake(schema)
            else:
                out = handler(system, user)
                try:
                    result = schema.model_validate(
                        out.model_dump() if isinstance(out, BaseModel) else out
                    )
                except Exception as exc:
                    raise LLMError(f"fake: handler output invalid ({type(exc).__name__})") from None
        except LLMError as exc:
            timer.failure(str(exc))
            raise
        timer.success(input_tokens=len(user) // 4, output_tokens=len(result.model_dump_json()) // 4)
        return result  # type: ignore[return-value]


# --- embedder ------------------------------------------------------------------------------------

_EMBED_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_LABEL_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z ]{2,30}:\s*", re.MULTILINE)
_EMBED_STOP = frozenset(
    "the and for with that this from your our are you les des une pour dans que qui est sur par "
    "nos vos aux ces ses leur plus avec sont ont pas mais comme tout tous".split()
)


def _embed_tokens(text: str) -> list[str]:
    # Drop "Label:" prefixes of the profile_text template: they are in every text and would only
    # raise the baseline similarity of unrelated companies.
    folded = fold(_LABEL_PREFIX_RE.sub("", text))
    out = []
    for tok in _EMBED_TOKEN_RE.findall(folded):
        if tok in _EMBED_STOP:
            continue
        out.append(tok[:-1] if len(tok) > 4 and tok.endswith("s") else tok)  # crude plural fold
    return out


def _bucket(feature: str, dim: int) -> tuple[int, float]:
    n = int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "big")
    return n % dim, (1.0 if (n >> 63) & 1 else -1.0)


class FakeEmbedder:
    """Signed hashing-trick bag of words (+ half-weight bigrams), L2-normalized."""

    name = "fake"
    model = "fake-hash-v1"

    def __init__(self, dim: int = 768, usage: UsageRecorder | None = None) -> None:
        self.dim = dim
        self._usage = usage

    def _vector(self, text: str) -> list[float]:
        tokens = _embed_tokens(text) or ["<empty>"]
        features: Counter[str] = Counter(tokens)
        features.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False))
        vec = np.zeros(self.dim, dtype=np.float64)
        for feature, count in features.items():
            idx, sign = _bucket(feature, self.dim)
            weight = (1.0 + math.log(count)) * (0.5 if " " in feature else 1.0)
            vec[idx] += sign * weight
        norm = float(np.linalg.norm(vec))
        if norm == 0.0:  # cancellation to exactly zero is possible in theory
            idx, _ = _bucket("<empty>", self.dim)
            vec[idx], norm = 1.0, 1.0
        return (vec / norm).tolist()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        timer = CallTimer(self._usage, provider=self.name, model=self.model, purpose="embedding")
        vectors = [self._vector(t) for t in texts]
        timer.success(input_tokens=sum(len(t) for t in texts) // 4)
        return vectors
