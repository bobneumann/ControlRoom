"""
Ops Board — spatial floor-plan view for Control Room.

Entities are placed at x/y fractions (0.0–1.0) on a background floor plan image.
Each entity shows an icon, label, and health dot driven by host_registry.

Designer mode: staging tray at bottom for unplaced entities; drag to place/move.
Live mode:     health dots + live clock; "N unplaced" badge if any remain.
"""

import os
import json
import math
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QFrame, QDialog, QFileDialog,
)
from PySide6.QtCore import Qt, QTimer, QRect, QRectF, QPointF, Signal
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QPixmap, QPainterPath,
    QRadialGradient, QBrush,
)

import host_registry


# ── icon set ─────────────────────────────────────────────────────────────────

ICON_KEYS = ["generic", "server", "switch", "camera", "speaker",
             "display", "controller", "nas"]


def _draw_icon(p: QPainter, icon: str, cx: float, cy: float,
               r: float, color: QColor) -> None:
    """Geometric icon centered at (cx, cy) with bounding radius r."""
    pen = QPen(color, max(1.2, r / 14))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    h = r * 0.52

    if icon == "server":
        p.drawRect(QRectF(cx - h, cy - h, h * 2, h * 0.82))
        p.drawRect(QRectF(cx - h, cy + h * 0.12, h * 2, h * 0.82))
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx + h * 0.52, cy - h * 0.45, r * 0.13, r * 0.13))
        p.drawEllipse(QRectF(cx + h * 0.52, cy + h * 0.55, r * 0.13, r * 0.13))

    elif icon == "switch":
        p.drawRect(QRectF(cx - h, cy - h * 0.38, h * 2, h * 0.76))
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        for i in range(4):
            px = cx - h * 0.72 + i * h * 0.48
            p.drawRect(QRectF(px, cy - h * 0.22, h * 0.28, h * 0.28))

    elif icon == "camera":
        p.drawRect(QRectF(cx - h * 0.85, cy - h * 0.5, h * 1.25, h))
        p.drawEllipse(QRectF(cx - h * 0.28, cy - h * 0.28, h * 0.56, h * 0.56))
        path = QPainterPath()
        path.moveTo(cx - h * 0.3, cy - h * 0.5)
        path.lineTo(cx - h * 0.12, cy - h * 0.82)
        path.lineTo(cx + h * 0.12, cy - h * 0.82)
        path.lineTo(cx + h * 0.3, cy - h * 0.5)
        p.drawPath(path)

    elif icon == "speaker":
        path = QPainterPath()
        path.moveTo(cx - h * 0.22, cy - h * 0.28)
        path.lineTo(cx - h * 0.22, cy + h * 0.28)
        path.lineTo(cx + h * 0.58, cy + h * 0.7)
        path.lineTo(cx + h * 0.58, cy - h * 0.7)
        path.closeSubpath()
        p.drawPath(path)
        p.drawArc(QRectF(cx + h * 0.48, cy - h * 0.55,
                         h * 0.52, h * 1.1), -55 * 16, 110 * 16)

    elif icon == "display":
        p.drawRect(QRectF(cx - h, cy - h * 0.72, h * 2, h * 1.18))
        p.drawLine(QPointF(cx, cy + h * 0.46), QPointF(cx, cy + h * 0.78))
        p.drawLine(QPointF(cx - h * 0.38, cy + h * 0.78),
                   QPointF(cx + h * 0.38, cy + h * 0.78))

    elif icon == "controller":
        p.drawRoundedRect(QRectF(cx - h, cy - h * 0.72, h * 2, h * 1.44),
                          r * 0.16, r * 0.16)
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - h * 0.38, cy - h * 0.14, r * 0.15, r * 0.15))
        p.drawEllipse(QRectF(cx + h * 0.16, cy - h * 0.14, r * 0.15, r * 0.15))

    elif icon == "nas":
        p.setBrush(Qt.NoBrush)
        for i in range(3):
            y = cy - h * 0.68 + i * h * 0.52
            p.drawRect(QRectF(cx - h, y, h * 2, h * 0.38))
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(cx + h * 0.58, y + h * 0.1,
                                  r * 0.11, r * 0.11))
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)

    else:  # generic
        p.drawEllipse(QRectF(cx - h, cy - h, h * 2, h * 2))
        p.drawLine(QPointF(cx, cy - h * 0.5), QPointF(cx, cy + h * 0.5))
        p.drawLine(QPointF(cx - h * 0.5, cy), QPointF(cx + h * 0.5, cy))


# ── sidebar style (standalone — avoids circular import with designer) ─────────

def _ops_sidebar_style(bg="#191c12", input_bg="#22261a", border="#404530",
                       fg="#c8bfa8", dim="#8a8270",
                       btn_bg="#2e3220", btn_border="#4e5238") -> str:
    return f"""
QWidget           {{ background-color: {bg}; color: {fg}; }}
QLabel            {{ color: {dim}; font-size: 9px; }}
QComboBox,
QLineEdit         {{ background: {input_bg}; color: {fg};
                     border: 1px solid {border}; padding: 2px 4px; }}
QComboBox QAbstractItemView
                  {{ background: {input_bg}; color: {fg};
                     selection-background-color: {btn_bg};
                     selection-color: #e8e0cc;
                     border: 1px solid {border}; }}
QPushButton       {{ background: {btn_bg}; color: {fg};
                     border: 1px solid {btn_border}; padding: 4px 8px; }}
QPushButton:hover {{ background: {btn_border}; }}
QFrame            {{ color: {btn_bg}; }}
"""


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class OpsEntity:
    key:   str
    label: str
    icon:  str            = "generic"
    x:     Optional[float] = None   # None = unplaced (staging tray)
    y:     Optional[float] = None


@dataclass
class OpsBoardLayout:
    background: str  = ""
    theme_key:  str  = "wwii"
    entities:   list = field(default_factory=list)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump({
                "background": self.background,
                "theme_key":  self.theme_key,
                "entities":   [asdict(e) for e in self.entities],
            }, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "OpsBoardLayout":
        with open(path) as f:
            d = json.load(f)
        entities = [OpsEntity(**e) for e in d.get("entities", [])]
        return cls(
            background = d.get("background", ""),
            theme_key  = d.get("theme_key", "wwii"),
            entities   = entities,
        )


def ops_board_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "ops_board.json")


# ── health helpers ────────────────────────────────────────────────────────────

_HEALTH_COLORS = {
    "good":       QColor(55,  210,  75),
    "warning":    QColor(200, 160,  40),
    "error":      QColor(210,  50,  50),
    "connecting": QColor(200, 160,  40),
}
_HEALTH_GRAY = QColor(75, 75, 75)


def _health_color(key: str) -> QColor:
    if not key:
        return _HEALTH_GRAY
    return _HEALTH_COLORS.get(host_registry.get_host_health(key), _HEALTH_GRAY)


# ── canvas constants ──────────────────────────────────────────────────────────

_TRAY_H   = 88    # staging tray height (edit mode)
_ENT_R    = 22    # entity icon bounding radius
_DOT_R    = 5     # health dot radius
_CHIP_W   = 118   # tray chip width
_CHIP_H   = 38    # tray chip height
_CHIP_PAD = 8     # gap between chips


# ── canvas ────────────────────────────────────────────────────────────────────

class OpsBoardCanvas(QWidget):
    entity_selected = Signal(int)   # -1 = deselected
    entity_clicked  = Signal(int)   # live-mode click on a placed entity

    def __init__(self, model: OpsBoardLayout, theme_info: dict, parent=None):
        super().__init__(parent)
        self._model     = model
        self._theme     = theme_info
        self._bg_pix    = None
        self._edit_mode = False
        self._selected  = -1

        self._drag_mode = None   # None | "from_tray" | "move"
        self._drag_idx  = -1
        self._drag_pos  = QPointF(0, 0)

        self.setMouseTracking(True)

        if model.background:
            self._load_bg(model.background)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(1000)

    # ── background ────────────────────────────────────────────────────────── #

    def _load_bg(self, path: str):
        pix = QPixmap(path)
        self._bg_pix = pix if not pix.isNull() else None

    def set_background(self, path: str):
        self._model.background = path
        self._load_bg(path)
        self.update()

    # ── public API ────────────────────────────────────────────────────────── #

    def set_theme(self, theme_info: dict):
        self._theme = theme_info
        self.update()

    def set_edit_mode(self, enabled: bool):
        self._edit_mode = enabled
        if not enabled:
            self._selected  = -1
            self._drag_mode = None
            self._drag_idx  = -1
            self.entity_selected.emit(-1)
        self.update()

    def load_model(self, model: OpsBoardLayout):
        self._model    = model
        self._selected = -1
        self._bg_pix   = None
        if model.background:
            self._load_bg(model.background)
        self.update()

    def save(self, path: str):
        self._model.save(path)

    def add_entity(self, entity: OpsEntity):
        self._model.entities.append(entity)
        self.update()

    def remove_entity(self, idx: int):
        if 0 <= idx < len(self._model.entities):
            del self._model.entities[idx]
            self._selected = -1
            self.entity_selected.emit(-1)
            self.update()

    def update_entity(self, idx: int, entity: OpsEntity):
        if 0 <= idx < len(self._model.entities):
            self._model.entities[idx] = entity
            self.update()

    # ── geometry ──────────────────────────────────────────────────────────── #

    def _canvas_rect(self) -> QRect:
        h = max(0, self.height() - (_TRAY_H if self._edit_mode else 0))
        return QRect(0, 0, self.width(), h)

    def _tray_rect(self) -> QRect:
        return QRect(0, self.height() - _TRAY_H, self.width(), _TRAY_H)

    def _entity_pixel(self, e: OpsEntity) -> QPointF:
        cr = self._canvas_rect()
        return QPointF(cr.x() + e.x * cr.width(),
                       cr.y() + e.y * cr.height())

    def _unplaced_indices(self) -> list:
        return [i for i, e in enumerate(self._model.entities) if e.x is None]

    def _chip_rect(self, chip_slot: int) -> QRect:
        tr = self._tray_rect()
        x  = tr.x() + _CHIP_PAD + chip_slot * (_CHIP_W + _CHIP_PAD)
        y  = tr.y() + (tr.height() - _CHIP_H) // 2
        return QRect(x, y, _CHIP_W, _CHIP_H)

    # ── paint ─────────────────────────────────────────────────────────────── #

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        cr = self._canvas_rect()
        p.fillRect(cr, QColor(self._theme.get("bg", "#2a2e1a")))

        if self._bg_pix:
            self._paint_bg_pixmap(p, cr)

        for i, e in enumerate(self._model.entities):
            if e.x is None:
                continue
            if self._drag_mode == "move" and self._drag_idx == i:
                continue
            pos = self._entity_pixel(e)
            self._paint_entity(p, pos.x(), pos.y(), e,
                               selected=(self._edit_mode and i == self._selected))

        if self._drag_mode is not None and self._drag_idx >= 0:
            e = self._model.entities[self._drag_idx]
            self._paint_entity(p, self._drag_pos.x(), self._drag_pos.y(),
                               e, ghost=True)

        if self._edit_mode:
            self._paint_tray(p)
        elif self._unplaced_indices():
            self._paint_unplaced_badge(p)

        self._paint_clock(p, cr)
        p.end()

    def _paint_bg_pixmap(self, p: QPainter, cr: QRect):
        pix  = self._bg_pix
        pw, ph = pix.width(), pix.height()
        scale  = min(cr.width() / pw, cr.height() / ph)
        dw = int(pw * scale)
        dh = int(ph * scale)
        dx = cr.x() + (cr.width()  - dw) // 2
        dy = cr.y() + (cr.height() - dh) // 2
        p.setOpacity(0.60)
        p.drawPixmap(QRect(dx, dy, dw, dh), pix)
        p.setOpacity(1.0)

    def _paint_entity(self, p: QPainter, cx: float, cy: float,
                      e: OpsEntity, selected: bool = False,
                      ghost: bool = False):
        alpha  = 110 if ghost else 255
        health = _health_color(e.key)
        hc     = QColor(health.red(), health.green(), health.blue(), alpha)

        # Glow halo
        grad = QRadialGradient(cx, cy, _ENT_R * 1.9)
        grad.setColorAt(0.0, QColor(health.red(), health.green(), health.blue(),
                                    45 if ghost else 65))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QRectF(cx - _ENT_R * 1.9, cy - _ENT_R * 1.9,
                             _ENT_R * 3.8, _ENT_R * 3.8))

        # Icon
        _draw_icon(p, e.icon, cx, cy, _ENT_R, QColor(215, 210, 195, alpha))

        # Health dot (top-right of icon)
        p.setPen(Qt.NoPen)
        p.setBrush(hc)
        p.drawEllipse(QRectF(cx + _ENT_R * 0.60 - _DOT_R,
                             cy - _ENT_R * 0.60 - _DOT_R,
                             _DOT_R * 2, _DOT_R * 2))

        # Label
        font = QFont("Arial Narrow", 8, QFont.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
        p.setFont(font)
        p.setPen(QColor(200, 195, 178, alpha))
        p.drawText(QRectF(cx - 60, cy + _ENT_R + 6, 120, 14),
                   Qt.AlignHCenter | Qt.AlignTop,
                   e.label.upper())

        # Selection ring
        if selected:
            p.setPen(QPen(QColor(210, 175, 80, 210), 2))
            p.setBrush(Qt.NoBrush)
            sel_r = _ENT_R + 5
            p.drawEllipse(QRectF(cx - sel_r, cy - sel_r, sel_r * 2, sel_r * 2))

    def _paint_tray(self, p: QPainter):
        tr      = self._tray_rect()
        t       = self._theme
        tray_bg = QColor(t.get("toolbar_bg", "#1a1e0e"))
        stripe  = QColor(t.get("div_stripe",  "#808060"))
        div_bg  = QColor(t.get("div_bg",      "#3a4020"))
        div_fg  = QColor(t.get("div_text",    "#c8bfa8"))

        p.fillRect(tr, tray_bg)
        p.fillRect(tr.x(), tr.y(), tr.width(), 2, stripe)

        font_lbl = QFont("Arial Narrow", 8, QFont.Bold)
        font_lbl.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(font_lbl)
        p.setPen(QColor(stripe.red(), stripe.green(), stripe.blue(), 130))
        p.drawText(QRect(tr.x() + 6, tr.y() + 5, 80, 14),
                   Qt.AlignLeft | Qt.AlignTop, "STAGING")

        chip_slot = 0
        for i, e in enumerate(self._model.entities):
            if e.x is not None:
                continue
            if self._drag_mode == "from_tray" and self._drag_idx == i:
                chip_slot += 1
                continue
            cr2 = self._chip_rect(chip_slot)
            p.fillRect(cr2, div_bg)
            p.setPen(QPen(stripe, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(cr2)
            _draw_icon(p, e.icon,
                       float(cr2.x() + 16), float(cr2.center().y()),
                       10.0, div_fg)
            font_chip = QFont("Arial Narrow", 8)
            p.setFont(font_chip)
            p.setPen(div_fg)
            p.drawText(QRect(cr2.x() + 30, cr2.y(),
                             cr2.width() - 34, cr2.height()),
                       Qt.AlignVCenter | Qt.AlignLeft,
                       e.label.upper()[:15])
            chip_slot += 1

    def _paint_unplaced_badge(self, p: QPainter):
        n = len(self._unplaced_indices())
        if not n:
            return
        text = f"{n} UNPLACED"
        font = QFont("Arial Narrow", 8, QFont.Bold)
        p.setFont(font)
        fm   = p.fontMetrics()
        bw   = fm.horizontalAdvance(text) + 16
        bh   = 20
        bx   = self.width() - bw - 10
        by   = self.height() - bh - 10
        p.fillRect(bx, by, bw, bh, QColor(175, 115, 25, 210))
        p.setPen(QColor(240, 220, 175))
        p.drawText(QRect(bx, by, bw, bh), Qt.AlignCenter, text)

    def _paint_clock(self, p: QPainter, cr: QRect):
        now  = datetime.now().strftime("%H:%M:%S")
        font = QFont("Arial Narrow", 10, QFont.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(font)
        fm   = p.fontMetrics()
        tw   = fm.horizontalAdvance(now)
        x    = cr.right() - tw - 12
        y    = cr.top() + 6
        p.setPen(QColor(0, 0, 0, 90))
        p.drawText(x + 1, y + fm.ascent() + 1, now)
        stripe = self._theme.get("div_stripe", "#808060")
        p.setPen(QColor(stripe))
        p.drawText(x, y + fm.ascent(), now)

    # ── mouse ─────────────────────────────────────────────────────────────── #

    def mousePressEvent(self, event):
        if not self._edit_mode:
            pos  = event.position()
            x, y = pos.x(), pos.y()
            for i in reversed(range(len(self._model.entities))):
                e = self._model.entities[i]
                if e.x is None:
                    continue
                ep = self._entity_pixel(e)
                if (x - ep.x()) ** 2 + (y - ep.y()) ** 2 <= (_ENT_R + 10) ** 2:
                    self.entity_clicked.emit(i)
                    return
            return
        pos  = event.position()
        x, y = pos.x(), pos.y()

        if self._tray_rect().contains(int(x), int(y)):
            chip_slot = 0
            for i, e in enumerate(self._model.entities):
                if e.x is not None:
                    continue
                if self._chip_rect(chip_slot).contains(int(x), int(y)):
                    self._drag_mode = "from_tray"
                    self._drag_idx  = i
                    self._drag_pos  = QPointF(x, y)
                    self._select(i)
                    return
                chip_slot += 1
            self._select(-1)
            return

        cr = self._canvas_rect()
        if cr.contains(int(x), int(y)):
            for i in reversed(range(len(self._model.entities))):
                e = self._model.entities[i]
                if e.x is None:
                    continue
                ep = self._entity_pixel(e)
                if (x - ep.x()) ** 2 + (y - ep.y()) ** 2 <= (_ENT_R + 8) ** 2:
                    self._drag_mode = "move"
                    self._drag_idx  = i
                    self._drag_pos  = QPointF(x, y)
                    self._select(i)
                    return
            self._select(-1)

    def mouseMoveEvent(self, event):
        if self._drag_mode is None:
            return
        self._drag_pos = event.position()
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_mode is None:
            return
        pos  = event.position()
        x, y = pos.x(), pos.y()
        cr   = self._canvas_rect()
        e    = self._model.entities[self._drag_idx]

        if self._drag_mode == "from_tray":
            if cr.contains(int(x), int(y)):
                e.x = max(0.0, min(1.0, (x - cr.x()) / cr.width()))
                e.y = max(0.0, min(1.0, (y - cr.y()) / cr.height()))
        elif self._drag_mode == "move":
            if self._tray_rect().contains(int(x), int(y)):
                e.x = None
                e.y = None
            elif cr.contains(int(x), int(y)):
                e.x = max(0.0, min(1.0, (x - cr.x()) / cr.width()))
                e.y = max(0.0, min(1.0, (y - cr.y()) / cr.height()))

        self._drag_mode = None
        self._drag_idx  = -1
        self.update()

    def _select(self, idx: int):
        self._selected = idx
        self.entity_selected.emit(idx)
        self.update()


# ── entity add/edit dialog ────────────────────────────────────────────────────

def _plain_dialog_style() -> str:
    return """
    QDialog     { background: #f0f0f0; }
    QWidget     { background: #f0f0f0; color: #000000; }
    QPushButton { background: #e1e1e1; color: black;
                  border: 1px solid #adadad; padding: 4px 12px; }
    QPushButton:hover   { background: #e8e8e8; }
    QPushButton:pressed { background: #cccccc; }
    QLineEdit { background: white; color: black;
                border: 1px solid #aaaaaa; padding: 2px 4px; }
    QComboBox { background: white; color: black;
                border: 1px solid #aaaaaa; padding: 2px 4px; }
    QComboBox QAbstractItemView { background: white; color: black; }
    QLabel { color: #333333; font-size: 9px; background: transparent; }
    """


def _entity_dialog(parent, title: str,
                   key: str = "", label: str = "",
                   icon: str = "generic") -> tuple:
    """Returns (key, label, icon, accepted)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(280)
    dlg.setStyleSheet(_plain_dialog_style())

    vbox = QVBoxLayout(dlg)

    vbox.addWidget(QLabel("LABEL"))
    label_edit = QLineEdit(label)
    label_edit.setPlaceholderText("e.g.  Q-SYS Core")
    vbox.addWidget(label_edit)

    vbox.addWidget(QLabel("MONITORED DEVICE"))
    key_combo = QComboBox()
    key_combo.addItem("— none —", "")
    for h in host_registry._active:
        key_combo.addItem(h.label, h.key)
    ci = key_combo.findData(key)
    key_combo.setCurrentIndex(ci if ci >= 0 else 0)
    vbox.addWidget(key_combo)

    vbox.addWidget(QLabel("ICON"))
    icon_combo = QComboBox()
    for ik in ICON_KEYS:
        icon_combo.addItem(ik)
    ci = icon_combo.findText(icon)
    if ci >= 0:
        icon_combo.setCurrentIndex(ci)
    vbox.addWidget(icon_combo)

    row = QHBoxLayout()
    ok_btn = QPushButton("OK")
    ok_btn.clicked.connect(dlg.accept)
    cancel_btn = QPushButton("Cancel")
    cancel_btn.clicked.connect(dlg.reject)
    row.addWidget(ok_btn)
    row.addWidget(cancel_btn)
    vbox.addLayout(row)

    accepted = dlg.exec() == QDialog.Accepted
    return (key_combo.currentData() or "",
            label_edit.text().strip(),
            icon_combo.currentText(),
            accepted)


# ── separator helper ──────────────────────────────────────────────────────────

def _sep() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Plain)
    return line


# ── sidebar ───────────────────────────────────────────────────────────────────

class OpsBoardSidebar(QWidget):
    def __init__(self, canvas: OpsBoardCanvas, path_fn=None, parent=None):
        super().__init__(parent)
        self._canvas   = canvas
        self._idx      = -1
        self._path_fn  = path_fn or ops_board_path
        self.setFixedWidth(220)
        self.setStyleSheet(_ops_sidebar_style())
        self._build_ui()
        canvas.entity_selected.connect(self._on_select)

    def set_style(self, css: str):
        self.setStyleSheet(css)

    def _build_ui(self):
        vbox = QVBoxLayout(self)
        vbox.setSpacing(6)
        vbox.setContentsMargins(10, 10, 10, 10)

        # Title
        self._title = QLabel("OPS BOARD")
        self._title.setAlignment(Qt.AlignCenter)
        f = self._title.font()
        f.setBold(True)
        f.setPointSize(10)
        self._title.setFont(f)
        self._title.setStyleSheet("color: #d4cbb8; letter-spacing: 2px;")
        vbox.addWidget(self._title)
        vbox.addWidget(_sep())

        # Background
        vbox.addWidget(QLabel("BACKGROUND IMAGE"))
        self._bg_label = QLabel("— none —")
        self._bg_label.setWordWrap(True)
        vbox.addWidget(self._bg_label)
        bg_btn = QPushButton("Set Background…")
        bg_btn.clicked.connect(self._set_background)
        vbox.addWidget(bg_btn)
        vbox.addWidget(_sep())

        # Selected entity section
        self._ent_section = QWidget()
        es = QVBoxLayout(self._ent_section)
        es.setContentsMargins(0, 0, 0, 0)
        es.setSpacing(6)

        es.addWidget(QLabel("LABEL"))
        self._lbl_edit = QLineEdit()
        es.addWidget(self._lbl_edit)

        es.addWidget(QLabel("ICON"))
        self._icon_combo = QComboBox()
        for ik in ICON_KEYS:
            self._icon_combo.addItem(ik)
        es.addWidget(self._icon_combo)

        es.addWidget(QLabel("MONITORED DEVICE"))
        self._key_combo = QComboBox()
        es.addWidget(self._key_combo)

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply)
        es.addWidget(apply_btn)

        self._del_btn = QPushButton("Delete Entity")
        self._del_btn.setStyleSheet(
            "QPushButton { color: #c06050; }"
            "QPushButton:hover { background: #3a2020; }"
        )
        self._del_btn.clicked.connect(self._delete)
        es.addWidget(self._del_btn)

        vbox.addWidget(self._ent_section)
        self._ent_section.setVisible(False)

        vbox.addWidget(_sep())

        add_btn = QPushButton("Add Entity")
        add_btn.clicked.connect(self._add_entity)
        vbox.addWidget(add_btn)

        vbox.addWidget(_sep())

        save_btn = QPushButton("Save Layout")
        save_btn.clicked.connect(self._save)
        vbox.addWidget(save_btn)

        load_btn = QPushButton("Load Layout")
        load_btn.clicked.connect(self._load)
        vbox.addWidget(load_btn)

        vbox.addStretch()

        done_btn = QPushButton("▶   LIVE MODE")
        done_btn.setStyleSheet(
            "QPushButton { background: #1e2e14; color: #90c060;"
            "              border: 1px solid #507840; font-weight: bold; padding: 6px; }"
            "QPushButton:hover { background: #2e3e20; }"
        )
        done_btn.clicked.connect(self._exit_edit)
        vbox.addWidget(done_btn)

    # ── selection ─────────────────────────────────────────────────────────── #

    def _refresh_key_combo(self, current_key: str = ""):
        self._key_combo.clear()
        self._key_combo.addItem("— none —", "")
        for h in host_registry._active:
            self._key_combo.addItem(h.label, h.key)
        ci = self._key_combo.findData(current_key)
        self._key_combo.setCurrentIndex(ci if ci >= 0 else 0)

    def _on_select(self, idx: int):
        self._idx = idx
        if idx < 0:
            self._title.setText("OPS BOARD")
            self._ent_section.setVisible(False)
            return

        e = self._canvas._model.entities[idx]
        self._title.setText(f"ENTITY {idx + 1}")
        self._lbl_edit.setText(e.label)
        self._refresh_key_combo(e.key)
        ci = self._icon_combo.findText(e.icon)
        if ci >= 0:
            self._icon_combo.setCurrentIndex(ci)
        self._ent_section.setVisible(True)

    # ── actions ───────────────────────────────────────────────────────────── #

    def _apply(self):
        if self._idx < 0:
            return
        old = self._canvas._model.entities[self._idx]
        self._canvas.update_entity(self._idx, OpsEntity(
            key   = self._key_combo.currentData() or "",
            label = self._lbl_edit.text().strip() or "ENTITY",
            icon  = self._icon_combo.currentText(),
            x     = old.x,
            y     = old.y,
        ))

    def _delete(self):
        if self._idx < 0:
            return
        self._canvas.remove_entity(self._idx)
        self._idx = -1

    def _add_entity(self):
        key, label, icon, ok = _entity_dialog(self, "Add Entity")
        if not ok:
            return
        self._canvas.add_entity(OpsEntity(
            key   = key,
            label = label or "ENTITY",
            icon  = icon,
        ))

    def _set_background(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Floor Plan Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self._canvas.set_background(path)
            self._bg_label.setText(os.path.basename(path))

    def _save(self):
        self._canvas.save(self._path_fn())

    def _load(self):
        p = self._path_fn()
        if os.path.exists(p):
            try:
                self._canvas.load_model(OpsBoardLayout.load(p))
                bg = self._canvas._model.background
                self._bg_label.setText(os.path.basename(bg) if bg else "— none —")
            except Exception:
                pass

    def _exit_edit(self):
        w = self.window()
        if hasattr(w, "set_edit_mode"):
            w.set_edit_mode(False)

    def sync_bg_label(self):
        bg = self._canvas._model.background
        self._bg_label.setText(os.path.basename(bg) if bg else "— none —")
