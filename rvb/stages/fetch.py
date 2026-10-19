"""Этап fetch: скачать исходники нужных версий (фреймворк и его зависимости)."""
from ..gitutil import git_head
from ..runner import run as run_cmd
from ..stamps import mark_done
from ..util import die, note, say

NAME = "fetch"
HELP = "скачать исходники фреймворка и зависимостей (git clone нужного тега)"
SKIP_IF_DONE = True


def _check_commit(entry, repo_dir, head):
    """Если в конфиге задан commit, убедиться, что тег всё ещё указывает на него."""
    expected = entry.get("commit")
    if expected and head != expected:
        die(f"{entry['name']}: в {repo_dir} коммит {head}, а в конфиге ожидается {expected}. "
            f"Тег {entry['version']} мог быть сдвинут, либо исходники изменены.")


def _fetch_one(ctx, entry):
    name, repo_dir = entry["name"], ctx.src_dir / entry["name"]
    if (repo_dir / ".git").exists():
        note(f"{name}: уже есть")
    else:
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        # --depth 1: берём только нужную версию, без всей истории (быстро и мало места)
        run_cmd(ctx, "fetch", ["git", "clone", "--branch", entry["version"], "--depth", "1",
                               entry["repo"], repo_dir])
        if entry.get("submodules", False):
            run_cmd(ctx, "fetch", ["git", "submodule", "update", "--init", "--recursive",
                                   "--depth", "1", "--jobs", "8"], cwd=repo_dir)
        note(f"{name} {entry['version']}: ok")
    _check_commit(entry, repo_dir, git_head(ctx, repo_dir))


def run(ctx):
    say("fetch: исходники")
    for entry in [ctx.fw["source"], *ctx.fw.get("deps", [])]:
        _fetch_one(ctx, entry)
    mark_done(ctx, NAME)
