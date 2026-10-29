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


NETWORK_ATTEMPTS = 2          # попыток на адрес: разовый таймаут не должен считаться отказом
NETWORK_TIMEOUT = 30          # секунд на попытку


def _check_network(ctx):
    """Проверить доступность адресов. Это только предупреждение, сборку оно не останавливает.

    Достаточно получить любой ответ сервера: даже HTTP 405 значит, что сеть работает.
    Адрес может отвечать медленно, а реальное скачивание (этапы bootstrap и fetch) ждёт дольше
    и повторяет попытки, поэтому недоступность здесь - повод посмотреть, а не остановиться.
    """
    urls = [ctx.toolchain["micromamba_url"], *ctx.host["check_urls"]]
    for url in urls:
        error = None
        for _attempt in range(NETWORK_ATTEMPTS):
            try:
                request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
                urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT).read(1)
                note(f"[ok] сеть: {url}")
                break
            except urllib.error.HTTPError as ex:
                note(f"[ok] сеть: {url} (ответ HTTP {ex.code})")
                break
            except Exception as ex:
                error = ex
        else:
            note(f"[??] сеть: {url} ({error}); не критично, нужный этап сам повторит попытку")


def run(ctx):
    say("doctor: проверка сервера")
    results = [
        _check_python(),
        _check_tools(),
        _check_disk(ctx),
    ]
    _check_network(ctx)                       # только предупреждения, на результат не влияет
    note(f"[ok] ядер: {os.cpu_count()}")
    if not all(results):
        die("doctor нашёл проблемы (см. [!!])")
