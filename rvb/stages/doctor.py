"""Этап doctor: проверить сервер, ничего не устанавливая."""
import os
import shutil
import sys
import urllib.error
import urllib.request

from ..util import die, note, say

NAME = "doctor"
HELP = "проверить сервер (Python, утилиты, диск, сеть); ничего не ставит"
SKIP_IF_DONE = False          # дешёвый, выполняется при каждом запуске


def _check_python():
    good = sys.version_info >= (3, 11)
    note(f"[{'ok' if good else '!!'}] Python {sys.version_info.major}.{sys.version_info.minor} (нужен >= 3.11, из-за tomllib)")
    return good


def _check_tools():
    good = True
    for tool in ["apt", "dpkg", "tar"]:
        found = shutil.which(tool) is not None
        note(f"[{'ok' if found else '!!'}] {tool}")
        good &= found
    return good


def _check_disk(ctx):
    """Свободное место: меньше min_disk_gb - ошибка, меньше comfortable_disk_gb - предупреждение."""
    ctx.work.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(ctx.work).free / 2**30
    minimum, comfortable = ctx.host["min_disk_gb"], ctx.host["comfortable_disk_gb"]
    mark = "ok" if free >= comfortable else ("??" if free >= minimum else "!!")
    note(f"[{mark}] свободно {free:.0f} ГБ (минимум {minimum}, комфортно {comfortable})")
    if minimum <= free < comfortable:
        note("    предупреждение: места впритык, следите за df -h во время сборки")
    return free >= minimum


def _check_network(ctx):
    """Достаточно получить любой ответ сервера: даже HTTP 405 значит, что сеть работает."""
    good = True
    urls = [ctx.toolchain["micromamba_url"], *ctx.host["check_urls"]]
    for url in urls:
        try:
            request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
            urllib.request.urlopen(request, timeout=15).read(1)
            note(f"[ok] сеть: {url}")
        except urllib.error.HTTPError as ex:
            note(f"[ok] сеть: {url} (ответ HTTP {ex.code})")
        except Exception as ex:
            note(f"[!!] сеть: {url} ({ex})")
            good = False
    return good


def run(ctx):
    say("doctor: проверка сервера")
    results = [
        _check_python(),
        _check_tools(),
        _check_disk(ctx),
        _check_network(ctx),
    ]
    note(f"[ok] ядер: {os.cpu_count()}")
    if not all(results):
        die("doctor нашёл проблемы (см. [!!])")
