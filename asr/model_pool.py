"""Bounded, thread-safe in-process ASR model reuse between VietDub jobs.

Only ONE pretrained model is retained. A shared per-model RLock guards
inference because FunASR and its speaker components may mutate internal
state; parallel calls to the same instance are deliberately serialized.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable


@dataclass
class CachedModel:
    key: tuple
    instance: Any
    inference_lock: RLock = field(default_factory=RLock)


_pool_lock = RLock()
_active: CachedModel | None = None


def acquire_model(key: tuple, loader: Callable[[], Any]):
    """Return (model, inference_lock, reused). Loader runs exactly once per key."""
    global _active
    if not isinstance(key, tuple):
        raise TypeError("ASR model pool key must be a tuple")
    with _pool_lock:
        if _active is not None and _active.key == key:
            return _active.instance, _active.inference_lock, True
        model = loader()
        if model is None:
            raise RuntimeError("FunASR model constructor returned None")
        _active = CachedModel(key=key, instance=model)
        return model, _active.inference_lock, False


def clear_model():
    """Release the retained model when user disables reuse or changes model."""
    global _active
    with _pool_lock:
        _active = None


def cache_info():
    with _pool_lock:
        return {"occupied": _active is not None,
                "key": _active.key if _active is not None else None}
