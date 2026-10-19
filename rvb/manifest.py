"""MANIFEST.txt - паспорт бандла: что собрано, из каких коммитов, с какими патчами."""
import time

from .gitutil import git_head
from .util import sha256


def write_manifest(ctx, out_dir):
    src = ctx.fw["source"]
    lines = [
        f"bundle: {ctx.framework} + {ctx.model_name}",
        f"built: {time.strftime('%F %T')}",
        f"board: {ctx.board['name']}",
        f"march: {ctx.board['arch']}",
        f"mtune: {ctx.board['tune']}",
        "",
        "[sources]",
        f"{src['name']} {src['version']} commit {git_head(ctx, ctx.src_dir / src['name'])}",
    ]
    for dep in ctx.fw.get("deps", []):
        lines.append(f"{dep['name']} {dep['version']} commit {git_head(ctx, ctx.src_dir / dep['name'])}")

    lines += ["", "[patches]"]
    for patch in ctx.fw.get("patches", []):
        patch_file = ctx.root / "patches" / ctx.framework / patch["file"]
        lines.append(f"{patch['file']} sha256 {sha256(patch_file)[:16]}  {patch['note']}")

    lines += ["", "[files] sha256(16) size name"]
    for path in sorted(out_dir.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.name != "MANIFEST.txt":
            lines.append(f"{sha256(path)[:16]} {path.stat().st_size:>10} {path.relative_to(out_dir)}")

    (out_dir / "MANIFEST.txt").write_text("\n".join(lines) + "\n")
