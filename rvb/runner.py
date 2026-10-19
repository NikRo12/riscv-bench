"""Запуск внешних команд: весь вывод пишется в лог этапа, на экране - только последняя строка."""
import subprocess
import sys

from .util import die

# В живом терминале показываем бегущую строку; при перенаправлении в файл (nohup) - не мусорим
_TTY = sys.stdout.isatty()


def run(ctx, log_name, cmd, cwd=None, check=True, env=None):
    """Запустить команду и вернуть её код возврата.

    log_name - имя файла в work/logs (без .log), туда дописывается команда и её вывод.
    check=True  - ненулевой код считается ошибкой: скрипт остановится и назовёт лог.
    check=False - код просто возвращается (так делает этап patch для пробного `git apply --check`).
    env         - своё окружение; по умолчанию ctx.env() (наши cmake/git и кросс-GCC).
    """
    ctx.logs.mkdir(parents=True, exist_ok=True)
    log = ctx.logs / f"{log_name}.log"
    printable = " ".join(str(c) for c in cmd)
    with open(log, "a") as lf:
        lf.write(f"\n$ {printable}   (cwd={cwd})\n")
        lf.flush()
        proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env or ctx.env(),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace")
        for line in proc.stdout:
            lf.write(line)
            if _TTY:
                print("\r\x1b[K" + line.rstrip()[:110], end="", flush=True)
        proc.wait()
        if _TTY:
            print("\r\x1b[K", end="")
    if check and proc.returncode != 0:
        die(f"команда упала (код {proc.returncode}): {printable[:200]}\nЛог: {log}")
    return proc.returncode
