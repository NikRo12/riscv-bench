"""Реестр этапов. Порядок здесь = порядок выполнения при `build.py all`.

Каждый этап - модуль с четырьмя именами:
    NAME          название этапа (то, что пишут в командной строке)
    HELP          одна строка для --help
    SKIP_IF_DONE  True: при `all` этап пропускается, если он уже выполнялся (метка в work/stamps)
    run(ctx)      сама работа

Чтобы добавить этап, создайте модуль по этому образцу и впишите его в STAGES.
"""
from . import bootstrap, build, doctor, fetch, package, patch, verify

STAGES = [doctor, bootstrap, fetch, patch, build, package, verify]
BY_NAME = {stage.NAME: stage for stage in STAGES}
