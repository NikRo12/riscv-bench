"""Чтение TOML-конфигов и проверка, что в них есть всё необходимое.

Проверка нужна, чтобы опечатка или забытый ключ в конфиге давала понятное
сообщение («в openvino.toml нет ключа 'repo'»), а не KeyError посреди сборки.
Описание всех ключей: docs/CONFIG.md.
"""
import tomllib

from .util import die


def load_toml(path):
    if not path.exists():
        die(f"нет файла конфигурации: {path}")
    with open(path, "rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as ex:
            die(f"ошибка синтаксиса в {path}: {ex}")


def _table(cfg, name, where):
    value = cfg.get(name)
    if not isinstance(value, dict):
        die(f"в {where} нет раздела [{name}] (см. docs/CONFIG.md)")
    return value


def _array(cfg, name, where):
    value = cfg.get(name)
    if not isinstance(value, list) or not value:
        die(f"в {where} нет ни одного блока [[{name}]] (см. docs/CONFIG.md)")
    return value


def _need(table, keys, where):
    for key in keys:
        if key not in table:
            die(f"в {where} нет ключа '{key}' (см. docs/CONFIG.md)")


def validate_target(cfg, where="configs/target.toml"):
    _need(_table(cfg, "board", where), ["name", "arch", "abi", "tune", "system_libs"], where + " [board]")
    _need(_table(cfg, "toolchain", where),
          ["cc", "cxx", "readelf", "micromamba_url", "conda_channel",
           "conda_packages", "cross_debs", "host_debs"], where + " [toolchain]")
    _need(_table(cfg, "host", where), ["min_disk_gb", "comfortable_disk_gb", "check_urls"], where + " [host]")


def validate_framework(cfg, where):
    _need(_table(cfg, "source", where), ["name", "repo", "version"], where + " [source]")
    for dep in cfg.get("deps", []):
        _need(dep, ["name", "repo", "version"], where + " [[deps]]")
    for patch in cfg.get("patches", []):
        _need(patch, ["file", "dir", "note"], where + " [[patches]]")
    for build in _array(cfg, "build", where):
        _need(build, ["name", "source", "build_dir"], where + " [[build]]")
    for bundle in _array(cfg, "bundle", where):
        _need(bundle, ["src", "patterns", "dest"], where + " [[bundle]]")
    run = _table(cfg, "run", where)
    _need(run, ["bench", "library_dirs", "command", "metrics"], where + " [run]")
    for metric in run["metrics"]:
        _need(metric, ["name", "pattern"], where + " [run] metrics")
    verify = _table(cfg, "verify", where)
    _need(verify, ["elf"], where + " [verify]")
    for item in verify.get("contains", []):
        _need(item, ["file", "strings"], where + " [[verify.contains]]")


def validate_model(cfg, where):
    _need(cfg, ["name", "dir", "files", "entry"], where)
    if cfg["entry"] not in cfg["files"]:
        die(f"в {where}: entry '{cfg['entry']}' должен быть в списке files")
