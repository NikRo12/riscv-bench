"""Генерация CMake toolchain-файла: он объясняет CMake, что мы собираем под RISC-V."""


def write_toolchain_file(ctx):
    board, tool = ctx.board, ctx.toolchain
    flags = f"-march={board['arch']} -mabi={board['abi']} -mtune={board['tune']}"
    ctx.toolchain_file.write_text(f"""# Сгенерировано build.py из configs/target.toml - руками не править
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR riscv64)

# sysroot: где лежат libc и заголовки для RISC-V (без него линкер не находит libc.so.6)
set(CMAKE_SYSROOT "{ctx.sysroot}")

set(CMAKE_C_COMPILER   {tool['cc']})
set(CMAKE_CXX_COMPILER {tool['cxx']})
set(CMAKE_C_FLAGS_INIT   "{flags}")
set(CMAKE_CXX_FLAGS_INIT "{flags}")

# программы ищем на сервере, библиотеки и заголовки - только в sysroot
set(CMAKE_FIND_ROOT_PATH "{ctx.sysroot}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE BOTH)
""")
