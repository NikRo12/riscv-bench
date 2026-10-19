"""Метки выполненных этапов: work/stamps/<фреймворк>.<этап>.

Нужны, чтобы повторный `build.py all` не качал и не собирал заново то, что уже сделано.
Принудительно повторить этап: `--force`.
"""
import time


def _path(ctx, stage):
    return ctx.stamps / f"{ctx.framework}.{stage}"


def is_done(ctx, stage):
    return _path(ctx, stage).exists() and not ctx.force


def mark_done(ctx, stage):
    ctx.stamps.mkdir(parents=True, exist_ok=True)
    _path(ctx, stage).write_text(time.strftime("%F %T\n"))
