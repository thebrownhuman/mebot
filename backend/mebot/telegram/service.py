"""Background Telegram workers, owned by the FastAPI lifespan.

A supervisor keeps one poller task per bot in polling mode (started/stopped when the
owner changes settings: ``reconcile()``), plus periodic loops (outbox sender, daily
digest) registered in ``LOOPS``. ``stop()`` cancels everything and releases leases.
Tests construct the app with TELEGRAM_WORKERS off and drive the pieces directly.
"""

import asyncio
import contextlib
import logging
import os
import uuid
from collections.abc import Awaitable, Callable

from mebot.telegram import outbox, repo
from mebot.telegram.poller import run_poller
from mebot.telegram.updates import TgContext

log = logging.getLogger(__name__)

SUPERVISE_EVERY = 30.0

# (name, coroutine(ctx) doing one round, seconds between rounds); filled by modules.
LOOPS: list[tuple[str, Callable[[TgContext], Awaitable[None]], float]] = [
    ("outbox", outbox.outbox_round, 2.0),
]


class TelegramService:
    def __init__(self, ctx: TgContext):
        self.ctx = ctx
        self.owner = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._pollers: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}
        self._tasks: list[asyncio.Task] = []
        self.running = False

    async def start(self) -> None:
        self.running = True
        self._tasks.append(asyncio.create_task(self._supervise(), name="tg-supervisor"))
        for name, fn, every in LOOPS:
            self._tasks.append(asyncio.create_task(self._loop(fn, every), name=f"tg-{name}"))

    def reconcile(self) -> None:
        """Settings changed: re-check which pollers should run (no-op when stopped)."""
        if self.running:
            self._wake.set()

    async def _loop(self, fn, every: float) -> None:
        while not self._stop.is_set():
            try:
                await fn(self.ctx)
            except Exception:  # noqa: BLE001 - keep the worker alive
                log.exception("telegram worker round failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=every)

    def _wanted(self) -> set[str]:
        with self.ctx.session_factory() as db:
            return {
                r.bot_id
                for r in repo.all_configured(db)
                if r.mode == "polling" and r.enabled and r.error is None
            }

    async def _supervise(self) -> None:
        while not self._stop.is_set():
            try:
                wanted = self._wanted()
                for bot_id in list(self._pollers):
                    task, stop = self._pollers[bot_id]
                    if bot_id not in wanted or task.done():
                        stop.set()
                        if task.done() or bot_id not in wanted:
                            self._pollers.pop(bot_id)
                for bot_id in wanted - set(self._pollers):
                    stop = asyncio.Event()
                    task = asyncio.create_task(
                        run_poller(self.ctx, bot_id, self.owner, stop), name=f"tg-poll-{bot_id}"
                    )
                    self._pollers[bot_id] = (task, stop)
            except Exception:  # noqa: BLE001
                log.exception("telegram supervisor failed")
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=SUPERVISE_EVERY)

    async def stop(self) -> None:
        self.running = False
        self._stop.set()
        self._wake.set()
        tasks = self._tasks + [t for t, _ in self._pollers.values()]
        for _, ev in self._pollers.values():
            ev.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._pollers.clear()
        self._tasks.clear()
