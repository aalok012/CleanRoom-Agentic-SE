"""Marshalling shim between JSON/DB primitives and Dafny's Python-runtime types.

`dafny translate py` emits *runtime-flavored* Python: strings are ``_dafny.Seq`` of code points
(not ``str``), maps are ``_dafny.Map`` (iterated via ``.keys.Elements``), and the ``_dafny``
runtime ships bundled inside each compiled ``<module>-py/`` directory. A thin FastAPI adapter that
wants to call a PROVED Dafny core therefore needs to convert request/DB values into those runtime
types and the result back out. This module is that converter — it is shipped INTO the generated
app so adapters import it instead of re-deriving the (fiddly, version-specific) conventions.

The conventions here were validated against real `dafny translate py` 4.11 output:
    str  -> _dafny.Seq(s)            ;  Dafny str -> seq.VerbatimString(False)
    int  -> int (passthrough)        ;  Dafny int -> int(x)
    map  -> _dafny.Map(...)          ;  Dafny map -> iterate m.keys.Elements, m[k]

``_dafny`` is imported lazily (it only exists on ``sys.path`` once a compiled core dir is added),
so importing this module in a plain environment never fails.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable


def _rt():
    """The bundled Dafny runtime (``_dafny``); raises a clear error if no compiled core is on path."""
    try:
        return importlib.import_module("_dafny")
    except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "Dafny runtime `_dafny` not importable — add a compiled `<module>-py/` dir to sys.path "
            "before using dafny_marshal (the adapter does this at startup)."
        ) from exc


def _identity(x: Any) -> Any:
    return x


# --- strings -------------------------------------------------------------------
def to_str(s: str):
    """python str -> Dafny ``seq<char>``."""
    return _rt().Seq(s)


def from_str(seq) -> str:
    """Dafny ``seq<char>`` -> python str."""
    return seq.VerbatimString(False)


# --- sequences -----------------------------------------------------------------
def to_seq(items, conv: Callable[[Any], Any] = _identity):
    """python list -> Dafny ``seq<T>`` (each element converted by ``conv``)."""
    return _rt().Seq([conv(x) for x in items])


def from_seq(seq, conv: Callable[[Any], Any] = _identity) -> list:
    """Dafny ``seq<T>`` -> python list (each element converted by ``conv``)."""
    return [conv(x) for x in seq.Elements]


# --- maps ----------------------------------------------------------------------
def to_map(d: dict, kconv: Callable[[Any], Any] = to_str, vconv: Callable[[Any], Any] = _identity):
    """python dict -> Dafny ``map<K,V>`` (keys/values converted by ``kconv``/``vconv``)."""
    rt = _rt()
    m = rt.Map({})
    for k, v in d.items():
        m = m.set(kconv(k), vconv(v))
    return m


def from_map(m, kconv: Callable[[Any], Any] = from_str, vconv: Callable[[Any], Any] = _identity) -> dict:
    """Dafny ``map<K,V>`` -> python dict (keys/values converted by ``kconv``/``vconv``)."""
    return {kconv(k): vconv(m[k]) for k in m.keys.Elements}
