"""
Пакеты контекста для ассистента.

Учёба: папка предмета, внутри подпапки работ. В каждой подпапке — любые .md/.txt/.py/.ipynb
(обычно EXPLANATION.md = шпаргалка + конспект ноутбука и README.md = задание).
Файл _common.md в корне папки добавляется к каждой работе (общая теория, метрики).

Собеседование: backend/profile.md + backend/job_description.md.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from answer_engine import ContextBundle

logger = logging.getLogger(__name__)

TEXT_EXT = {".md", ".txt", ".py"}
COMMON_NAMES = ("_common.md", "COMMON.md", "_общее.md")
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass
class Lab:
    name: str
    folder: str
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)


def _read_ipynb(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            nb = json.load(f)
    except Exception as e:
        logger.warning(f"Не удалось прочитать ноутбук {path}: {e}")
        return ""
    parts = []
    for cell in nb.get("cells", []):
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else src
        if not src.strip():
            continue
        if cell.get("cell_type") == "markdown":
            parts.append(src.strip())
        elif cell.get("cell_type") == "code":
            n = cell.get("execution_count")
            parts.append(f"Ячейка In [{n}]:\n```python\n{src.strip()}\n```")
            outs = []
            for o in cell.get("outputs", []):
                if o.get("output_type") == "stream":
                    outs.append("".join(o.get("text", "")))
                elif "text/plain" in o.get("data", {}) and "image/png" not in o.get("data", {}):
                    outs.append("".join(o["data"]["text/plain"]))
            out = "\n".join(x.rstrip() for x in outs if x.strip())[:1500]
            if out:
                parts.append(f"Вывод In [{n}]:\n```\n{out}\n```")
    return "\n\n".join(parts)


def _read_folder(folder: str) -> str:
    parts = []
    # README первым, EXPLANATION вторым, остальное по алфавиту
    def order(name: str):
        up = name.upper()
        return (0 if up.startswith("README") else 1 if up.startswith("EXPLANATION") else 2, name)

    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fname in sorted(files, key=order):
            if fname.startswith(".") or fname in COMMON_NAMES:
                continue
            path = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()
            rel = os.path.relpath(path, folder)
            try:
                if ext in TEXT_EXT:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                elif ext == ".ipynb":
                    content = _read_ipynb(path)
                else:
                    continue
            except Exception as e:
                logger.warning(f"Пропускаю {path}: {e}")
                continue
            if content.strip():
                parts.append(f"=== Файл: {rel} ===\n\n{content.strip()}")
    return "\n\n".join(parts)


class StudyPack:
    def __init__(self):
        self.folder: str = ""
        self.common: str = ""
        self.labs: list[Lab] = []
        self.active: int = -1

    def load(self, folder: str) -> None:
        folder = folder.strip("\r\n\t")
        if not os.path.isdir(folder):
            raise ValueError(f"Папка не найдена: {folder}")
        self.folder = folder
        self.common = ""
        for name in COMMON_NAMES:
            p = os.path.join(folder, name)
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    self.common = f.read()
                break
        labs = []
        for entry in sorted(os.listdir(folder)):
            sub = os.path.join(folder, entry)
            if entry.startswith(".") or not os.path.isdir(sub):
                continue
            text = _read_folder(sub)
            if text.strip():
                labs.append(Lab(name=entry, folder=sub, text=text))
        if not labs:
            text = _read_folder(folder)
            if text.strip():
                labs.append(Lab(name=os.path.basename(folder.rstrip("/")) or "Работа", folder=folder, text=text))
        self.labs = labs
        self.active = 0 if labs else -1
        logger.info(f"Пакет загружен: {folder}, работ: {len(labs)}, общая часть: {len(self.common)} симв.")

    def bundle(self) -> ContextBundle:
        if not (0 <= self.active < len(self.labs)):
            return ContextBundle(mode="study", title="", text=self.common)
        lab = self.labs[self.active]
        others = [l.name for i, l in enumerate(self.labs) if i != self.active]
        text = (f"СЕЙЧАС ЗАЩИЩАЕТСЯ РАБОТА: {lab.name}"
                + (f" (другие работы этой КТ: {', '.join(others)} — если спросят про них, ответь кратко по общей части)" if others else "")
                + f"\n\n{lab.text}")
        if self.common:
            text += f"\n\n=== ОБЩАЯ ЧАСТЬ (для всех работ) ===\n\n{self.common}"
        return ContextBundle(mode="study", title=lab.name, text=text)

    def info(self) -> dict:
        return {
            "folder": self.folder,
            "active": self.active,
            "labs": [{"index": i, "name": l.name, "chars": l.chars} for i, l in enumerate(self.labs)],
            "common_chars": len(self.common),
        }


def interview_bundle() -> ContextBundle:
    def read(name, fallback):
        p = os.path.join(BACKEND_DIR, name)
        try:
            with open(p, "r", encoding="utf-8") as f:
                t = f.read().strip()
                return t or fallback
        except FileNotFoundError:
            return fallback
    profile = read("profile.md", "[профиль не заполнен — backend/profile.md]")
    job = read("job_description.md", "[вакансия не заполнена — backend/job_description.md]")
    return ContextBundle(mode="interview", title="Собеседование",
                         text=f"ПРОФИЛЬ КАНДИДАТА:\n{profile}\n\nВАКАНСИЯ:\n{job}")
