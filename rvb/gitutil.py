"""Мелкие вызовы git. Используется git из micromamba (его ставит этап bootstrap)."""
import subprocess


def git_head(ctx, repo_dir):
    """Хеш текущего коммита репозитория или «?», если узнать не удалось."""
    result = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
                            env=ctx.env(), capture_output=True, text=True)
    return result.stdout.strip() or "?"
