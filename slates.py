"""
Slate Manager — named bundles of (instrument panel layout + ops board layout).

Each slate is a named profile that can be switched instantly.  Layout files
are stored in the project directory; slates.json is the index.

On first run, any existing layout.json / ops_board.json are wrapped into a
"Default" slate automatically so nothing is lost.
"""

import os
import json
import re
import shutil
from dataclasses import dataclass, field, asdict
from typing import Optional


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower().strip())
    slug = re.sub(r"[\s-]+", "_", slug)
    return slug or "slate"


@dataclass
class Slate:
    name:           str
    description:    str = ""
    layout_file:    str = ""        # relative to project dir
    ops_board_file: str = ""        # relative to project dir


class SlateManager:
    _FILE = "slates.json"

    def __init__(self, base_dir: str):
        self._base   = base_dir
        self._slates: list = []
        self._active: str  = ""
        self._load()

    # ── persistence ───────────────────────────────────────────────────────── #

    def _path(self) -> str:
        return os.path.join(self._base, self._FILE)

    def _load(self):
        p = self._path()
        if os.path.exists(p):
            try:
                with open(p) as f:
                    d = json.load(f)
                self._slates = [Slate(**s) for s in d.get("slates", [])]
                self._active = d.get("active", "")
                if self._slates and self._active not in self.names:
                    self._active = self._slates[0].name
                return
            except Exception:
                pass

        # Migration: wrap existing files into a "Default" slate
        default = Slate(
            name           = "Default",
            description    = "Main layout",
            layout_file    = "layout.json"
                             if os.path.exists(os.path.join(self._base, "layout.json"))
                             else "",
            ops_board_file = "ops_board.json"
                             if os.path.exists(os.path.join(self._base, "ops_board.json"))
                             else "",
        )
        self._slates = [default]
        self._active = "Default"
        self.save()

    def save(self):
        with open(self._path(), "w") as f:
            json.dump(
                {"active": self._active,
                 "slates": [asdict(s) for s in self._slates]},
                f, indent=2,
            )

    # ── read API ──────────────────────────────────────────────────────────── #

    @property
    def names(self) -> list:
        return [s.name for s in self._slates]

    @property
    def active_slate(self) -> Optional[Slate]:
        for s in self._slates:
            if s.name == self._active:
                return s
        return self._slates[0] if self._slates else None

    def get(self, name: str) -> Optional[Slate]:
        return next((s for s in self._slates if s.name == name), None)

    def layout_path(self) -> str:
        s = self.active_slate
        if s and s.layout_file:
            return os.path.join(self._base, s.layout_file)
        return os.path.join(self._base, "layout.json")

    def ops_board_path(self) -> str:
        s = self.active_slate
        if s and s.ops_board_file:
            return os.path.join(self._base, s.ops_board_file)
        return os.path.join(self._base, "ops_board.json")

    # ── write API ─────────────────────────────────────────────────────────── #

    def set_active(self, name: str):
        if name in self.names:
            self._active = name
            self.save()

    def new_slate(self, name: str, description: str = "",
                  copy_from: Optional[Slate] = None) -> Slate:
        slug = _slugify(name)
        lf   = f"layout_{slug}.json"
        obf  = f"ops_board_{slug}.json"
        if copy_from:
            for src_rel, dst_rel in [(copy_from.layout_file,    lf),
                                      (copy_from.ops_board_file, obf)]:
                if src_rel:
                    src = os.path.join(self._base, src_rel)
                    if os.path.exists(src):
                        shutil.copy2(src, os.path.join(self._base, dst_rel))
        slate = Slate(name=name, description=description,
                      layout_file=lf, ops_board_file=obf)
        self._slates.append(slate)
        self.save()
        return slate

    def rename_slate(self, old_name: str, new_name: str):
        s = self.get(old_name)
        if s:
            s.name = new_name
            if self._active == old_name:
                self._active = new_name
            self.save()

    def update_description(self, name: str, description: str):
        s = self.get(name)
        if s:
            s.description = description
            self.save()

    def delete_slate(self, name: str):
        if len(self._slates) <= 1:
            return   # never delete the last slate
        self._slates = [s for s in self._slates if s.name != name]
        if self._active == name:
            self._active = self._slates[0].name
        self.save()
