"""Этап patch: наложить патчи на исходники (безопасно и повторяемо).

Для каждого патча:
    1. `git apply --check`      - пробный прогон, файлы не меняются;
    2. проходит                 - применяем настоящим `git apply`;
    3. не проходит, но проходит `git apply --check -R` (отмена) - патч уже применён, пропускаем;
    4. иначе                    - исходники отличаются от тех, для которых делался патч: остановка.
"""
from ..runner import run as run_cmd
from ..stamps import mark_done
from ..util import die, note, say

NAME = "patch"
HELP = "наложить патчи из patches/<фреймворк>/ (повторный запуск безопасен)"
SKIP_IF_DONE = True


def _apply(ctx, patch):
    repo = ctx.src_dir / patch.get("repo", ctx.fw["source"]["name"])
    # patch["dir"] - внутри репозитория; для подмодуля это его папка (у него свой git)
    target_dir = (repo / patch["dir"]).resolve()
    patch_file = ctx.root / "patches" / ctx.framework / patch["file"]
    if not patch_file.exists():
        die(f"нет файла патча {patch_file}")

    check = ["git", "-C", target_dir, "apply", "--check", patch_file]
    if run_cmd(ctx, "patch", check, check=False) == 0:
        run_cmd(ctx, "patch", ["git", "-C", target_dir, "apply", patch_file])
        note(f"применён: {patch['file']}")
    elif run_cmd(ctx, "patch", ["git", "-C", target_dir, "apply", "--check", "-R", patch_file], check=False) == 0:
        note(f"уже применён: {patch['file']}")
    else:
        die(f"патч {patch['file']} не ложится на исходники (версия изменилась?). "
            f"Лог: {ctx.logs / 'patch.log'}")


def run(ctx):
    say("patch: применение патчей")
    for patch in ctx.fw.get("patches", []):
        _apply(ctx, patch)
    mark_done(ctx, NAME)
