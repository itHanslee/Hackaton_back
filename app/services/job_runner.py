"""Ejecutor acotado de tareas en background (evita threads daemon ilimitados)."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="medinote_job")


def submit_background(fn: Callable, *args, **kwargs) -> Future:
    return _executor.submit(fn, *args, **kwargs)
