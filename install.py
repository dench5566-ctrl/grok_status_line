#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Поставить строку состояния Grok на этот Mac.

Копирует statusline.py в ~/.grok/statusline.py.
В ~/.grok/config.toml меняет только таблицу [ui.status_line].
Остальные ключи файла не трогает.
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "statusline.py")
GROK_HOME = os.path.expanduser("~/.grok")
DEST = os.path.join(GROK_HOME, "statusline.py")
CONFIG = os.path.join(GROK_HOME, "config.toml")

BLOCK = (
    "[ui.status_line]\n"
    'type = "command"\n'
    'command = "/usr/bin/python3 ~/.grok/statusline.py"\n'
    "padding = 0\n"
    "refresh_interval = 10\n"
)


def is_header(line):
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def replace_section(text):
    lines = text.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.strip() == "[ui.status_line]":
            start = index
            break
    if start is None:
        body = text
        if body and not body.endswith("\n"):
            body += "\n"
        if body and not body.endswith("\n\n"):
            body += "\n"
        return body + BLOCK
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if is_header(lines[index]):
            end = index
            break
    head = "".join(lines[:start])
    tail = "".join(lines[end:])
    merged = head + BLOCK
    if tail:
        if not merged.endswith("\n"):
            merged += "\n"
        if not merged.endswith("\n\n"):
            merged += "\n"
        merged += tail
    return merged


def section_already_set(text):
    needle = BLOCK.strip()
    return needle in text


def main():
    if not os.path.isfile(SRC):
        sys.stderr.write("Рядом нет statusline.py\n")
        return 1
    os.makedirs(GROK_HOME, exist_ok=True)
    shutil.copyfile(SRC, DEST)
    os.chmod(DEST, 0o755)

    if os.path.isfile(CONFIG):
        with open(CONFIG, encoding="utf-8") as handle:
            current = handle.read()
    else:
        current = ""

    if section_already_set(current):
        updated = current
        config_note = "Блок [ui.status_line] уже такой, файл не переписан."
    else:
        updated = replace_section(current)
        with open(CONFIG, "w", encoding="utf-8") as handle:
            handle.write(updated)
        config_note = "В ~/.grok/config.toml записан только блок [ui.status_line]."

    sys.stdout.write(
        "Скрипт лежит в ~/.grok/statusline.py\n"
        + config_note
        + "\n"
        "Правка скрипта видна на следующем обновлении строки.\n"
        "Правка config.toml видна после нового запуска Grok.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
