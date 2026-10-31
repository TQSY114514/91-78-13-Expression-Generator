import tkinter as tk
from tkinter import font as tkfont
import itertools
import math
import queue
import sys
import threading
import time
from bisect import bisect_left, bisect_right

# ====== 开启高分屏 DPI 感知 (彻底解决 Windows 下字体发虚) ======
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# ====== Claude / Anthropic 暖调学术美学配色 ======
CLR_BG = "#F8F7F4"          # 经典羊皮纸暖白 (Claude Background)
CLR_SURFACE = "#F1F0EC"     # 浅暖灰次级表面
CLR_PRIME = "#20201E"       # 深炭黑墨水色 (Claude Primary Text)
CLR_ACCENT = "#C87554"      # 标志性赤陶暖橙 (Claude Terracotta Accent)
CLR_MUTED = "#77766F"       # 柔和石板灰 (副标题/提示语)
CLR_BORDER = "#E3E1DB"      # 极细微暖色描边
CLR_SELECT_BG = "#E8DFD5"   # 柔和暖调学术选区背景 (Claude Selection Tint)


class FontManager:
    """自动探测系统中最接近 Claude / Amp 的高品质衬线与等宽字体"""
    def __init__(self, root):
        available = set(tkfont.families(root))

        # Claude 正文/标题衬线字体栈 (Tiempos / Charter / Palatino / Book Antiqua / Georgia)
        serif_candidates = [
            "Tiempos Text", "Tiempos Headline", "Charter", "Bitstream Charter",
            "Iowan Old Style", "Book Antiqua", "Palatino Linotype", "Palatino",
            "Baskerville", "Georgia", "Times New Roman"
        ]
        # 优雅等宽/数学符号字体栈
        mono_candidates = [
            "Berkeley Mono", "JetBrains Mono", "Fira Code",
            "Cascadia Mono", "Consolas", "Courier New"
        ]

        self.serif = next((f for f in serif_candidates if f in available), "Georgia")
        self.mono = next((f for f in mono_candidates if f in available), "Consolas")



class SmoothNumericEntry(tk.Canvas):
    """
    自绘数字输入框：
    - Canvas 自绘光标，使用缓动插值实现平滑移动；
    - 颜色渐变模拟 smooth caret blinking；
    - 支持数字输入、方向键、Home/End、退格、删除、鼠标定位、
      拖动选择、Ctrl+A/C/X/V。
    """
    def __init__(self, master, font, bg, fg, caret_color, select_bg, select_fg,
                 height=58, **kwargs):
        super().__init__(
            master, height=height, bg=bg, bd=0, highlightthickness=0,
            takefocus=True, **kwargs
        )
        self.font = tkfont.Font(font=font)
        self.bg_color = bg
        self.fg_color = fg
        self.caret_color = caret_color
        self.select_bg = select_bg
        self.select_fg = select_fg

        self.value = ""
        self.caret = 0
        self.anchor = 0
        self.visual_x = 12.0
        self.scroll_x = 0.0
        self.target_scroll_x = 0.0
        self.focused = False
        self.dragging = False
        self.blink_phase = 0.0
        self._animation_job = None
        self.blink_phase_value = 1.0
        self._caret_item = None
        self._caret_fill = None
        self._baseline = 0.0
        self._tx_key = None
        self._tx = 12.0
        self.copy_fallback = None   # 无选区时 Ctrl+C 的回退动作（复制结果表达式）

        self.bind("<KeyPress>", self._on_key)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Double-Button-1>", self._on_double)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Control-a>", self._select_all)
        self.bind("<Control-A>", self._select_all)
        self.bind("<Control-c>", self._copy)
        self.bind("<Control-C>", self._copy)
        self.bind("<Control-x>", self._cut)
        self.bind("<Control-X>", self._cut)
        self.bind("<Control-v>", self._paste)
        self.bind("<Control-V>", self._paste)
        self.bind("<Return>", self._submit)
        self.bind("<KP_Enter>", self._submit)
        self._redraw()
        self._animate()

    def get(self):
        return self.value

    def delete(self, first, last=None):
        # 兼容常见 Entry.delete(0, END) 调用。
        self.value = ""
        self.caret = self.anchor = 0
        self._changed()

    def insert(self, index, text):
        text = "".join(ch for ch in str(text) if ch.isdigit())
        if not text:
            return
        index = self._index(index)
        self._replace_selection("")
        self.value = self.value[:index] + text + self.value[index:]
        self.caret = self.anchor = index + len(text)
        self._changed()

    def _index(self, index):
        if index in ("end", tk.END):
            return len(self.value)
        try:
            return max(0, min(len(self.value), int(index)))
        except (TypeError, ValueError):
            return self.caret

    def _selection(self):
        return min(self.caret, self.anchor), max(self.caret, self.anchor)

    def _replace_selection(self, replacement):
        start, end = self._selection()
        if start != end:
            self.value = self.value[:start] + replacement + self.value[end:]
            self.caret = self.anchor = start + len(replacement)
            return True
        return False

    def _changed(self):
        self.target_scroll_x = self._desired_scroll()
        self.blink_phase = 0.0
        self._redraw()
        self.event_generate("<<InputChanged>>", when="tail")

    def _desired_scroll(self):
        width = max(1, self.winfo_width() - 24)
        caret_x = 12 + self.font.measure(self.value[:self.caret])
        if caret_x - self.target_scroll_x > width - 8:
            return max(0, caret_x - width + 8)
        if caret_x - self.target_scroll_x < 8:
            return max(0, caret_x - 8)
        return self.target_scroll_x

    def _x_to_index(self, x):
        content_x = x + self.scroll_x - 12
        if content_x <= 0:
            return 0
        total_w = self.font.measure(self.value)
        if content_x >= total_w:
            return len(self.value)
        for i in range(len(self.value) + 1):
            left = self.font.measure(self.value[:i])
            right = self.font.measure(self.value[:i + 1])
            if i == len(self.value) or content_x < (left + right) / 2:
                return i
        return len(self.value)

    def _on_click(self, event):
        self.focus_set()
        self.caret = self.anchor = self._x_to_index(event.x)
        self.dragging = True
        self.blink_phase = 0.0
        self.blink_phase_value = 1.0
        self.target_scroll_x = self._desired_scroll()
        self._redraw()

    def _on_drag(self, event):
        if self.dragging:
            self.caret = self._x_to_index(event.x)
            self.target_scroll_x = self._desired_scroll()
            self._redraw()

    def _on_release(self, _event):
        self.dragging = False

    def _on_focus_in(self, _event=None):
        self.focused = True
        self.blink_phase = 0.0
        self._redraw()

    def _on_focus_out(self, _event=None):
        self.focused = False
        self._redraw()

    def _select_all(self, _event=None):
        self.anchor, self.caret = 0, len(self.value)
        self._redraw()
        return "break"

    def _copy(self, _event=None):
        start, end = self._selection()
        if start != end:
            self.clipboard_clear()
            self.clipboard_append(self.value[start:end])
        elif self.copy_fallback is not None:
            self.copy_fallback()
        return "break"

    def _cut(self, _event=None):
        self._copy()
        if self._selection()[0] != self._selection()[1]:
            self._replace_selection("")
            self._changed()
        return "break"

    def _paste(self, _event=None):
        try:
            pasted = self.clipboard_get()
        except tk.TclError:
            return "break"
        pasted = "".join(ch for ch in pasted if ch.isdigit())
        if pasted:
            self._replace_selection("")
            pos = self.caret
            self.value = self.value[:pos] + pasted + self.value[pos:]
            self.caret = self.anchor = pos + len(pasted)
            self._changed()
        return "break"

    def _submit(self, _event=None):
        self.event_generate("<<Submit>>", when="tail")
        return "break"

    def _on_key(self, event):
        key = event.keysym
        shift = bool(event.state & 0x0001)

        if key in ("Left", "Right", "Home", "End"):
            if key == "Home":
                self.caret = 0
            elif key == "End":
                self.caret = len(self.value)
            elif key == "Left":
                if not shift and self._selection()[0] != self._selection()[1]:
                    self.caret = self._selection()[0]
                else:
                    self.caret = max(0, self.caret - 1)
            elif key == "Right":
                if not shift and self._selection()[0] != self._selection()[1]:
                    self.caret = self._selection()[1]
                else:
                    self.caret = min(len(self.value), self.caret + 1)
            if not shift:
                self.anchor = self.caret
            self.target_scroll_x = self._desired_scroll()
            self.blink_phase = 0.0
            self._redraw()
            return "break"

        if key == "BackSpace":
            if not self._replace_selection(""):
                if self.caret > 0:
                    self.value = self.value[:self.caret - 1] + self.value[self.caret:]
                    self.caret -= 1
                    self.anchor = self.caret
            self._changed()
            return "break"

        if key == "Delete":
            if not self._replace_selection(""):
                if self.caret < len(self.value):
                    self.value = self.value[:self.caret] + self.value[self.caret + 1:]
            self._changed()
            return "break"

        if key in ("Return", "KP_Enter"):
            return self._submit()

        if event.char and event.char.isdigit() and len(event.char) == 1:
            self._replace_selection("")
            pos = self.caret
            self.value = self.value[:pos] + event.char + self.value[pos:]
            self.caret = self.anchor = pos + 1
            self.blink_phase = 0.0
            self.blink_phase_value = 1.0
            self._changed()
            return "break"

        # 屏蔽非数字字符，保留 Ctrl/Alt 等系统快捷键。
        if event.char and event.char.isprintable() and not (event.state & 0x0004):
            return "break"
        return None

    @staticmethod
    def _mix_color(a, b, amount):
        a = a.lstrip("#")
        b = b.lstrip("#")
        vals = [
            round(int(a[i:i+2], 16) * (1 - amount) + int(b[i:i+2], 16) * amount)
            for i in (0, 2, 4)
        ]
        return "#{:02x}{:02x}{:02x}".format(*vals)

    def _on_double(self, _event=None):
        self.dragging = False
        self.anchor, self.caret = 0, len(self.value)
        self.blink_phase = 0.0
        self._redraw()
        return "break"

    def _caret_x(self):
        # font.measure 较慢：仅在文本或光标位置变化时重新测量。
        key = (self.value, self.caret)
        if key != self._tx_key:
            self._tx_key = key
            self._tx = 12 + self.font.measure(self.value[:self.caret])
        return self._tx

    def _caret_color(self):
        amount = 0.25 + 0.75 * self.blink_phase_value
        amount = round(amount * 24) / 24   # 量化：颜色没变就不必重绘
        return self._mix_color(self.bg_color, self.caret_color, amount)

    def _redraw(self):
        # 显式调用 Canvas.delete，避免与输入框兼容接口 delete() 冲突。
        tk.Canvas.delete(self, "all")
        height = max(1, self.winfo_height())
        baseline = height / 2
        self._baseline = baseline
        text_x = 12 - self.scroll_x

        start, end = self._selection()
        sx = text_x + self.font.measure(self.value[:start]) if start != end else 0
        if start != end:
            ex = text_x + self.font.measure(self.value[:end])
            self.create_rectangle(sx, 8, ex, height - 8, fill=self.select_bg, outline="")
        self.create_text(
            text_x, baseline, anchor="w", text=self.value,
            font=self.font, fill=self.fg_color
        )
        if start != end:
            self.create_text(
                sx, baseline, anchor="w", text=self.value[start:end],
                font=self.font, fill=self.select_fg
            )

        self._caret_item = None
        if self.focused:
            cx = self.visual_x - self.scroll_x
            self._caret_fill = self._caret_color()
            self._caret_item = self.create_line(
                cx, baseline - 15, cx, baseline + 15,
                fill=self._caret_fill, width=1.6
            )

    def _animate(self):
        # 只有滚动位置变化才整体重绘；光标移动/闪烁只更新一条线。
        target_x = self._caret_x()
        old_scroll = self.scroll_x
        dx = target_x - self.visual_x
        ds = self.target_scroll_x - self.scroll_x
        moving = abs(dx) > 0.15 or abs(ds) > 0.15
        self.visual_x = self.visual_x + dx * 0.32 if abs(dx) > 0.15 else target_x
        self.scroll_x = self.scroll_x + ds * 0.24 if abs(ds) > 0.15 else self.target_scroll_x

        if self.focused:
            # phase=0 时最亮：输入、点击后光标立即清晰可见，再平滑淡出/淡入。
            self.blink_phase = (self.blink_phase + 0.11) % (2 * math.pi)
            self.blink_phase_value = 0.5 + 0.5 * math.cos(self.blink_phase)
            if self.scroll_x != old_scroll or self._caret_item is None:
                self._redraw()
            else:
                cx = self.visual_x - self.scroll_x
                self.coords(self._caret_item, cx, self._baseline - 15, cx, self._baseline + 15)
                fill = self._caret_color()
                if fill != self._caret_fill:
                    self.itemconfigure(self._caret_item, fill=fill)
                    self._caret_fill = fill
        delay = 16 if moving else (33 if self.focused else 120)
        self._animation_job = self.after(delay, self._animate)

    def destroy(self):
        if self._animation_job is not None:
            try:
                self.after_cancel(self._animation_job)
            except tk.TclError:
                pass
            self._animation_job = None
        super().destroy()


class SolveCancelled(Exception):
    """搜索被新的输入取消。"""


# 数字拆分规则：去掉运算符后的数字流必须恰好是 91、78、13 的顺序拼接，
# 但每个操作数可以在原子中间断开（如 9*1、137*8）。
# 因此每个子表达式带“对齐类型”：
#   st: 'A' 从原子边界开始；否则以某原子的第二位数字（'1'/'8'/'3'）开头
#   en: 'A' 在原子边界结束；否则结尾留着某原子的第一位数字（'9'/'7'/'1'），下一段必须补全
# 两段相接合法 <=> _REQ[left.en] == right.st。
_REQ = {"A": "A", "9": "1", "7": "8", "1": "3"}
_ATOMS = ("91", "78", "13")


class _Expr:
    """
    表达式树节点。叶子是一段连续数字；运算符连接左右两段（左段数字在前）。

    kind: "a" 数字叶子, "s" 加减链, "m" 乘除链。
    length/parens 是最终打印形式的字符数/括号数，对子树可加，所以搜索时无需拼字符串。
    hd: 乘除链按打印顺序是否含 "/"（决定能否作为除数内联）。
    """
    __slots__ = ("value", "kind", "op", "left", "right", "literal",
                 "length", "parens", "st", "en", "hd")

    def __init__(self, value, kind, op, left, right, literal,
                 length, parens, st, en, hd):
        self.value = value
        self.kind = kind
        self.op = op
        self.left = left
        self.right = right
        self.literal = literal
        self.length = length
        self.parens = parens
        self.st = st
        self.en = en
        self.hd = hd

    @classmethod
    def leaf(cls, digits, st="A", en="A"):
        return cls(int(digits), "a", None, None, None, digits, len(digits), 0, st, en, False)

    # ------------------------------------------------------------ 输出
    # 打印严格保持叶子的原始数字顺序（否则会破坏 9*1 这类跨原子的拆分）。
    def _terms(self, sign, out):
        if self.kind == "s":
            self.left._terms(sign, out)
            self.right._terms(sign if self.op == "+" else -sign, out)
        else:
            out.append((sign, self))

    def _items(self):
        """乘除链按顺序展开为 [(运算符, 文本)]，首项运算符固定为 '*' 占位。"""
        items = self.left._operand_items(False)
        items += self.right._operand_items(self.op == "/")
        return items

    def _operand_items(self, invert):
        if self.kind == "m" and (not invert or not self.hd):
            items = self._items()
            if invert:  # a/(b*c) -> a/b/c（此处 b*c 内只有乘号，翻转后全是除号）
                items = [("*" if op == "/" else "/", t) for op, t in items]
            return items
        text = self.render()
        if self.kind != "a":
            text = "(" + text + ")"
        return [("/" if invert else "*", text)]

    def render(self):
        kind = self.kind
        if kind == "a":
            return self.literal
        if kind == "s":
            terms = []
            self._terms(1, terms)
            out = terms[0][1].render()
            for sign, node in terms[1:]:
                out += ("+" if sign > 0 else "-") + node.render()
            return out
        items = self._items()
        return items[0][1] + "".join(op + t for op, t in items[1:])


def _combine(left, right, op):
    """(value, kind, length, parens, hd)；不合法（负数/不整除/除零）返回 None。"""
    a, b = left.value, right.value
    if op == "+":
        value, kind = a + b, "s"
    elif op == "-":
        if a < b:
            return None
        value, kind = a - b, "s"
    elif op == "*":
        value, kind = a * b, "m"
    else:
        if b == 0 or a % b:
            return None
        value, kind = a // b, "m"
    length = left.length + right.length + 1
    parens = left.parens + right.parens
    hd = False
    if kind == "m":
        if left.kind == "s":
            length += 2
            parens += 1
        if right.kind == "s" or (op == "/" and right.kind == "m" and right.hd):
            length += 2
            parens += 1
        hd = op == "/" or (left.kind == "m" and left.hd) or (right.kind == "m" and right.hd)
    return value, kind, length, parens, hd


def _make(left, right, op, info):
    value, kind, length, parens, hd = info
    return _Expr(value, kind, op, left, right, None, length, parens, left.st, right.en, hd)


def _merge(out, left, right, op):
    """out 的键为 kind（调用方保证候选数值相同）。"""
    info = _combine(left, right, op)
    if info is None:
        return
    old = out.get(info[1])
    if old is None or (info[2], info[3]) < (old.length, old.parens):
        out[info[1]] = _make(left, right, op, info)


def _better(old, expr):
    return old is None or (expr.length, expr.parens) < (old.length, old.parens)


class FinalArtAlgo:
    """
    用 91、78、13 构造非负整数表达式。

    - 数位级 DP：枚举所有“可成为某合法数字流子串”的数字段作为操作数（支持 9*1、137*8
      这类跨原子拆分），带对齐类型组合，确保拼合后去掉符号仍严格由 91、78、13 组成。
    - 更大的数：字面量/紧凑乘积邻近、小因数分解、多基底商余/补数搜索（确定性剪枝）。
    - 打印按数字顺序展开链式运算，只保留必要括号。
    - 每个结果由独立 AST 求值器复核（除法逐步整除），并校验数字流。
    """

    VALUE_CAP = 10 ** 10

    def __init__(self):
        self.atoms = _ATOMS
        self.atom_values = {int(x): x for x in _ATOMS}
        self._aligned_lits = self._build_aligned_literals()
        self._leaves = self._build_leaves(8)
        self._bank = {}
        self.exact_cache = {}
        self.memo = {}
        self._should_cancel = None
        self._enrich_started = False

        # 首屏构建：1~5 位完整层 + 6 位完整对齐层（约 180ms，在后台 worker 线程中先于窗口完成）
        self._extend_bank(5, self._bank)
        self._bank[6] = self._build_aligned_layer(6, self._bank)
        self._refresh_tables(self._bank)

    # ------------------------------------------------------------ 构建
    @staticmethod
    def _build_aligned_literals():
        lits = []
        for length in (1, 2, 3, 4):
            for seq in itertools.product(_ATOMS, repeat=length):
                s = "".join(seq)
                lits.append((int(s), _Expr.leaf(s)))
        lits.sort(key=lambda x: x[0])
        return lits

    @staticmethod
    def _build_leaves(max_digits):
        """所有合法数字流的子串，连同其对齐类型，按位数分组。"""
        found = set()
        for k in range(1, (max_digits + 1) // 2 + 1):
            for seq in itertools.product(_ATOMS, repeat=k):
                s = "".join(seq)
                for i in range(len(s)):
                    for j in range(i + 1, min(len(s), i + max_digits) + 1):
                        st = "A" if i % 2 == 0 else s[i]
                        en = "A" if j % 2 == 0 else s[j - 1]
                        found.add((s[i:j], st, en))
        by_len = {}
        for digits, st, en in sorted(found):
            by_len.setdefault(len(digits), []).append((digits, st, en))
        return by_len

    def _extend_bank(self, upto, bank):
        for d in range(1, upto + 1):
            if d not in bank:
                bank[d] = self._build_bank_layer(d, bank)

    def _build_bank_layer(self, d, bank):
        cap = self.VALUE_CAP
        layer = {}
        for digits, st, en in self._leaves.get(d, ()):
            e = _Expr.leaf(digits, st, en)
            if e.value <= cap:
                layer[(e.value, "a", st, en)] = e
        for d1 in range(1, d):
            d2 = d - d1
            by_start = {}
            for e in bank[d2].values():
                by_start.setdefault(e.st, []).append(e)
            for left in list(bank[d1].values()):
                rights = by_start.get(_REQ[left.en])
                if not rights:
                    continue
                for right in rights:
                    for op in ("+", "-", "*", "/"):
                        info = _combine(left, right, op)
                        if info is None or info[0] > cap:
                            continue
                        key = (info[0], info[1], left.st, right.en)
                        old = layer.get(key)
                        if old is None or (info[2], info[3]) < (old.length, old.parens):
                            layer[key] = _make(left, right, op, info)
        return layer

    def _build_aligned_layer(self, d, bank, pairs=None, max_extra=None):
        """只构建首尾均对齐 (st='A', en='A') 的偶数位层，省去不会复用的中间边界状态。"""
        cap = self.VALUE_CAP
        layer = {}
        for digits, st, en in self._leaves.get(d, ()):
            if st == "A" and en == "A":
                e = _Expr.leaf(digits, "A", "A")
                if e.value <= cap:
                    layer[(e.value, "a", "A", "A")] = e
        if pairs is None:
            pairs = [(d1, d - d1) for d1 in range(1, d)]
        for d1, d2 in pairs:
            lim1 = d1 + max_extra if max_extra is not None else 999
            lim2 = d2 + max_extra if max_extra is not None else 999
            by_start = {}
            for e in bank[d2].values():
                if e.en == "A" and e.length <= lim2:
                    by_start.setdefault(e.st, []).append(e)
            for left in bank[d1].values():
                if left.st != "A" or left.length > lim1:
                    continue
                for right in by_start.get(_REQ[left.en], ()):
                    for op in ("+", "-", "*", "/"):
                        info = _combine(left, right, op)
                        if info is None or info[0] > cap:
                            continue
                        key = (info[0], info[1], "A", "A")
                        old = layer.get(key)
                        if old is None or (info[2], info[3]) < (old.length, old.parens):
                            layer[key] = _make(left, right, op, info)
        return layer

    def _refresh_tables(self, bank):
        cache = self._make_cache(bank)
        divisors = self._make_divisors(cache)
        bases, anchors = self._make_bases_and_anchors(cache)
        self._cheap_divisors = divisors
        self.bases = bases
        self.literals = anchors
        self._lit_values = [v for v, _ in anchors]
        self.exact_cache = cache

    def _make_cache(self, bank):
        """只取首尾都对齐的表达式作为可复用的构件。"""
        cache = {}
        for layer in bank.values():
            for (value, kind, st, en), e in layer.items():
                if st == "A" and en == "A":
                    bucket = cache.setdefault(value, {})
                    if _better(bucket.get(kind), e):
                        bucket[kind] = e
        self._augment_small(cache)
        return cache

    @staticmethod
    def _augment_small(cache):
        """保证 0~90 每个数都有表达式（用 13/13、78/13、91/13 累加补齐）。"""
        a13, a78, a91 = (_Expr.leaf(x) for x in _ATOMS[::-1])
        units = []
        for num in (a13, a78, a91):
            out = {}
            _merge(out, num, a13, "/")
            units.extend(out.values())
        for number in range(1, 91):
            bucket = cache.setdefault(number, {})
            for unit in units:
                prev = cache.get(number - unit.value)
                if prev and number - unit.value > 0:
                    for p in list(prev.values()):
                        _merge(bucket, p, unit, "+")
        zero = {}
        _merge(zero, a13, a13, "-")
        cache.setdefault(0, {}).update(zero)
        for number in [k for k, v in cache.items() if not v]:
            del cache[number]

    @staticmethod
    def _make_divisors(cache):
        return [v for v in range(2, 4000)
                if v in cache and min(e.length for e in cache[v].values()) <= 9]

    def _make_bases_and_anchors(self, cache):
        """提取 5 字符以内的无括号紧凑乘积与字面量作为商余基底与邻近锚点（如 917*8、789*1）。"""
        base_map = {v: (e.length, v, e) for v, e in self._aligned_lits if v <= 10 ** 6}
        anchor_map = {v: e for v, e in self._aligned_lits}
        for v, bucket in cache.items():
            if v < 100:
                continue
            e = bucket.get("m")
            if e is None or e.parens > 0 or e.hd or e.length > 5:
                continue
            if v <= 10 ** 6:
                old = base_map.get(v)
                if old is None or e.length < old[0]:
                    base_map[v] = (e.length, v, e)
            old_a = anchor_map.get(v)
            if old_a is None or e.length < old_a.length:
                anchor_map[v] = e
        anchors = sorted(anchor_map.items(), key=lambda x: x[0])
        return list(base_map.values()), anchors

    def start_background(self):
        """窗口显示后再补全 8 位对齐层，避免拖慢启动。"""
        if self._enrich_started:
            return
        self._enrich_started = True
        threading.Thread(target=self._enrich, daemon=True).start()

    def _enrich(self):
        try:
            if 8 in self._bank:
                return
            bank = dict(self._bank)
            bank[8] = self._build_aligned_layer(
                8, bank, pairs=((2, 6), (6, 2), (4, 4)), max_extra=1
            )
            self._bank = bank
            self._refresh_tables(bank)
            self.memo = {}      # 旧结果基于较浅的缓存，清空以获得更短表达式
        except Exception:
            pass

    # ------------------------------------------------------------ 搜索
    def _estimate(self, x, cache):
        if x == 0:
            return 0
        hit = cache.get(x)
        if hit:
            return min(e.length for e in hit.values())
        return 4 * len(str(x))

    def _cands(self, n):
        cache = self.exact_cache
        hit = cache.get(n)
        if hit:
            return hit
        hit = self.memo.get(n)
        if hit:
            return hit
        if self._should_cancel is not None and self._should_cancel():
            raise SolveCancelled()

        out = {}
        cands = self._cands

        # 1. 邻近锚点：n = L ± d
        window = 3000
        lo = bisect_left(self._lit_values, n - window)
        hi = bisect_right(self._lit_values, n + window)
        for idx in range(lo, hi):
            value, lit = self.literals[idx]
            d = n - value
            if d == 0:
                continue
            if d > 0:
                for de in cands(d).values():
                    _merge(out, lit, de, "+")
            elif -d < n:
                for de in cands(-d).values():
                    _merge(out, lit, de, "-")

        # 2. 因数分解：n = v * (n / v)，v 取表达式短的小数
        if n < 10 ** 7:
            for v in self._cheap_divisors:
                if v * v > n:
                    break
                if n % v == 0:
                    for ve in cands(v).values():
                        for qe in cands(n // v).values():
                            _merge(out, ve, qe, "*")
                            _merge(out, qe, ve, "*")

        # 3. 多基底商余 / 补数：n = b*q + r 或 b*(q+1) - gap
        plans = []
        for blen, b, _ in self.bases:
            q, r = divmod(n, b)
            if q > 0:
                plans.append((blen + self._estimate(q, cache) + self._estimate(r, cache), b, q, r, False))
            gap = (q + 1) * b - n if r else 0
            if 0 < gap < n:
                plans.append((blen + 2 + self._estimate(q + 1, cache) + self._estimate(gap, cache), b, q + 1, gap, True))
        plans.sort(key=lambda p: p[0])
        keep = 6 if n < 10 ** 6 else 4
        base_expr = {b: e for _, b, e in self.bases}
        for _, b, q, r, upward in plans[:keep]:
            be = base_expr[b]
            # q == 1 时乘积就是基底本身，无需再乘 1。
            q_choices = (None,) if q == 1 else tuple(cands(q).values())
            for qe in q_choices:
                if qe is None:
                    prod = {be.kind: be}
                else:
                    prod = {}
                    _merge(prod, be, qe, "*")
                if not prod:
                    continue
                if r == 0:
                    for p in prod.values():
                        if _better(out.get(p.kind), p):
                            out[p.kind] = p
                    continue
                for re in cands(r).values():
                    for p in prod.values():
                        _merge(out, p, re, "-" if upward else "+")

        if not out:
            raise ValueError(f"无法构造数字 {n} 的表达式")
        self.memo[n] = out
        return out

    # ------------------------------------------------------------ 对外
    def solve(self, n, should_cancel=None):
        n = int(n)
        if n < 0:
            raise ValueError("请输入非负整数")
        self._should_cancel = should_cancel
        try:
            best = min(self._cands(n).values(), key=lambda e: (e.length, e.parens))
        finally:
            self._should_cancel = None
        text = best.render()
        # 独立复核：AST 求值（逐步整除）必须等于 n，且去掉运算符后的数字流只含原子。
        if self._evaluate(text) != n:
            raise ValueError("内部校验失败：表达式求值与目标不符")
        if not self._is_atomic_sequence(text):
            raise ValueError("内部校验失败：生成的表达式不符合原子规则")
        return text

    def _is_atomic_sequence(self, expr):
        """去掉所有运算符/括号后，数字流必须恰好是 91、78、13 的顺序拼接。"""
        digits = "".join(ch for ch in expr if ch.isdigit())
        if not digits or len(digits) % 2:
            return False
        return all(digits[i:i + 2] in self.atoms for i in range(0, len(digits), 2))

    @staticmethod
    def _evaluate(expr):
        """严格求值：按文本的左结合顺序计算，每个除法必须整除。"""
        import ast  # 惰性导入：只在首次校验时付出代价，加快窗口启动
        tree = ast.parse(expr, mode="eval")

        def visit(node):
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.Constant) and type(node.value) is int:
                return node.value
            if isinstance(node, ast.BinOp):
                a, b = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add):
                    return a + b
                if isinstance(node.op, ast.Sub):
                    return a - b
                if isinstance(node.op, ast.Mult):
                    return a * b
                if isinstance(node.op, ast.Div):
                    if b == 0 or a % b:
                        raise ValueError("non-integer division")
                    return a // b
            raise ValueError("unsupported expression")

        return visit(tree)


class FrierenGrimoire:
    """无边框桌面窗口：Claude 的纸感 + Amp 的轻量工具感。"""

    def __init__(self, root):
        self.root = root
        self.root.title("Numeric Proof")
        self.root.overrideredirect(True)
        self.root.configure(bg=CLR_BORDER)

        self.fonts = FontManager(self.root)
        self.algo = None          # 在后台线程中构建，窗口不必等待
        self.current_formula = ""
        self._task = None
        self.typing_task = None
        self.anim_task = None
        self.is_dragging = False
        self.drag_offset = (0, 0)
        self.eq_angle = 0.0
        self.eq_target = 0.0
        self.type_generation = 0

        width, height = 720, 590
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x, y = (sw - width) // 2, (sh - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(600, 500)

        self.setup_ui()
        self._start_worker()
        self.root.bind("<Escape>", lambda _event: self.root.destroy())
        self.root.bind("<Control-Return>", lambda _event: self.solve_logic())
        self.root.bind("<Configure>", self._on_configure)
        self._animate_eq()

    def setup_ui(self):
        # 1px 暖灰外沿代替系统窗口边框，保持无边框视觉。
        self.shell = tk.Frame(self.root, bg=CLR_BG)
        self.shell.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 自定义顶部栏：可拖动，右侧关闭。
        self.header = tk.Frame(self.shell, bg=CLR_BG, height=42)
        self.header.pack(fill=tk.X, padx=30, pady=(13, 0))
        self.header.pack_propagate(False)

        self.brand = tk.Label(
            self.header, text="N U M E R I C   P R O O F",
            font=(self.fonts.mono, 9, "bold"),
            fg=CLR_MUTED, bg=CLR_BG
        )
        self.brand.pack(side=tk.LEFT, anchor="center")

        self.close_btn = tk.Label(
            self.header, text="×", font=(self.fonts.serif, 19),
            fg=CLR_MUTED, bg=CLR_BG, padx=8, cursor="hand2"
        )
        self.close_btn.pack(side=tk.RIGHT)
        self.close_btn.bind("<Button-1>", lambda _e: self.root.destroy())
        self.close_btn.bind("<Enter>", lambda _e: self.close_btn.configure(fg=CLR_ACCENT))
        self.close_btn.bind("<Leave>", lambda _e: self.close_btn.configure(fg=CLR_MUTED))

        for widget in (self.header, self.brand):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)

        tk.Frame(self.shell, bg=CLR_BORDER, height=1).pack(fill=tk.X, padx=30, pady=(7, 0))

        self.content = tk.Frame(self.shell, bg=CLR_BG)
        self.content.pack(fill=tk.BOTH, expand=True, padx=48, pady=(30, 25))

        tk.Label(
            self.content, text="Find a proof.",
            font=(self.fonts.serif, 30),
            fg=CLR_PRIME, bg=CLR_BG, anchor="w"
        ).pack(fill=tk.X)

        tk.Label(
            self.content,
            text="Construct an expression from the atoms 91, 78 and 13.",
            font=(self.fonts.serif, 11),
            fg=CLR_MUTED, bg=CLR_BG, anchor="w"
        ).pack(fill=tk.X, pady=(7, 25))

        tk.Label(
            self.content, text="NUMBER",
            font=(self.fonts.mono, 9, "bold"),
            fg=CLR_MUTED, bg=CLR_BG, anchor="w"
        ).pack(fill=tk.X, pady=(0, 8))

        input_row = tk.Frame(
            self.content, bg=CLR_SURFACE,
            highlightthickness=1, highlightbackground=CLR_BORDER
        )
        input_row.pack(fill=tk.X)

        self.entry = SmoothNumericEntry(
            input_row, font=(self.fonts.mono, 23),
            bg=CLR_SURFACE, fg=CLR_PRIME, caret_color=CLR_ACCENT,
            select_bg=CLR_SELECT_BG, select_fg=CLR_PRIME, height=58
        )
        self.entry.pack(fill=tk.X, padx=16, pady=12)
        self.entry.bind("<<InputChanged>>", self.handle_input)
        self.entry.bind("<<Submit>>", lambda _event: self.solve_logic())
        self.entry.focus_set()
        self.entry.copy_fallback = self.copy_formula

        # 轻量等号动效：输入时从水平转向竖直，保留原版的动态反馈。
        self.eq_canvas = tk.Canvas(
            self.content, width=72, height=42, bg=CLR_BG,
            highlightthickness=0, bd=0
        )
        self.eq_canvas.pack(pady=(5, 1))
        self.eq_line_a = self.eq_canvas.create_line(0, 0, 0, 0, fill=CLR_ACCENT, width=2.0, capstyle=tk.ROUND)
        self.eq_line_b = self.eq_canvas.create_line(0, 0, 0, 0, fill=CLR_ACCENT, width=2.0, capstyle=tk.ROUND)

        result_head = tk.Frame(self.content, bg=CLR_BG)
        result_head.pack(fill=tk.X, pady=(5, 9))
        tk.Label(
            result_head, text="EXPRESSION",
            font=(self.fonts.mono, 9, "bold"),
            fg=CLR_MUTED, bg=CLR_BG
        ).pack(side=tk.LEFT)
        tk.Label(
            result_head, text="CLICK TO COPY",
            font=(self.fonts.mono, 8),
            fg=CLR_MUTED, bg=CLR_BG
        ).pack(side=tk.RIGHT)

        result_shell = tk.Frame(
            self.content, bg=CLR_SURFACE,
            highlightthickness=1, highlightbackground=CLR_BORDER
        )
        result_shell.pack(fill=tk.BOTH, expand=True)

        self.res_txt = tk.Text(
            result_shell, font=(self.fonts.mono, 13),
            fg=CLR_PRIME, bg=CLR_SURFACE, bd=0,
            highlightthickness=0, wrap=tk.WORD,
            padx=18, pady=17, cursor="hand2", state=tk.DISABLED
        )
        self.res_txt.pack(fill=tk.BOTH, expand=True)
        self.res_txt.tag_configure("formula", foreground=CLR_PRIME, justify="left")
        self.res_txt.bind("<Button-1>", self.copy_formula)
        self._scroll_target = 0.0
        self._scroll_job = None
        self.res_txt.bind("<MouseWheel>", self._smooth_result_scroll)
        self.res_txt.bind("<Button-4>", lambda _e: self._smooth_result_scroll_linux(-1))
        self.res_txt.bind("<Button-5>", lambda _e: self._smooth_result_scroll_linux(1))

        footer = tk.Frame(self.content, bg=CLR_BG)
        footer.pack(fill=tk.X, pady=(13, 0))
        self.status = tk.Label(
            footer, text="Ready · Enter a number to begin",
            font=(self.fonts.mono, 9), fg=CLR_MUTED,
            bg=CLR_BG, anchor="w"
        )
        self.status.pack(side=tk.LEFT)

        self.copy_button = tk.Label(
            footer, text="Copy  ↗", font=(self.fonts.mono, 9),
            fg=CLR_PRIME, bg=CLR_BG, padx=4, pady=3, cursor="hand2"
        )
        self.copy_button.pack(side=tk.RIGHT)
        self.copy_button.bind("<Button-1>", self.copy_formula)
        self.copy_button.bind("<Enter>", lambda _e: self.copy_button.configure(fg=CLR_ACCENT))
        self.copy_button.bind("<Leave>", lambda _e: self.copy_button.configure(fg=CLR_PRIME))

    def _smooth_result_scroll_linux(self, direction):
        self._queue_result_scroll(direction * 3)
        return "break"

    def _smooth_result_scroll(self, event):
        # Windows delta 通常为 120；触控板的小幅 delta 也能平滑累积。
        units = -event.delta / 120 * 3
        if abs(units) < 0.15:
            units = -1 if event.delta > 0 else 1
        self._queue_result_scroll(units)
        return "break"

    def _queue_result_scroll(self, units):
        try:
            total = max(1, int(self.res_txt.count("1.0", "end", "displaylines")[0]))
        except (TypeError, IndexError, tk.TclError):
            total = 20
        self._scroll_target = max(0.0, min(1.0, self._scroll_target + units / total))
        if self._scroll_job is None:
            self._animate_result_scroll()

    def _animate_result_scroll(self):
        current = self.res_txt.yview()[0]
        delta = self._scroll_target - current
        if abs(delta) < 0.001:
            self.res_txt.yview_moveto(self._scroll_target)
            self._scroll_job = None
            return
        self.res_txt.yview_moveto(current + delta * 0.28)
        self._scroll_job = self.root.after(16, self._animate_result_scroll)

    def start_drag(self, event):
        self.is_dragging = True
        self.drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def do_drag(self, event):
        if self.is_dragging:
            x = event.x_root - self.drag_offset[0]
            y = event.y_root - self.drag_offset[1]
            self.root.geometry(f"+{x}+{y}")

    def _on_configure(self, _event=None):
        # 保留钩子供后续响应式布局使用；不做边缘检测或自动回弹。
        pass

    # ------------------------------------------------------------ 状态栏
    def _set_status(self, text, fg, remember=True):
        self.status.configure(text=text, fg=fg)
        if remember:
            self._status_state = (text, fg)

    # ------------------------------------------------------------ 后台求解
    def _start_worker(self):
        self._cv = threading.Condition()
        self._req = None
        self._req_id = 0
        self._done_id = 0
        self._results = queue.SimpleQueue()
        self._poll_job = None
        self._busy_job = None
        self._status_state = ("Ready · Enter a number to begin", CLR_MUTED)
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        algo = FinalArtAlgo()
        self.algo = algo
        enriched = False
        while True:
            with self._cv:
                if self._req is None and not enriched:
                    self._cv.wait(timeout=0.20)
                if self._req is None and not enriched:
                    enriched = True
                    need_enrich = True
                else:
                    need_enrich = False
                    while self._req is None:
                        self._cv.wait()
                    req_id, number = self._req
                    self._req = None
            if need_enrich:
                algo._enrich()
                continue

            def stale(rid=req_id):
                # 有更新的输入到来时，立刻放弃当前搜索。
                return self._req is not None or rid != self._req_id

            t0 = time.perf_counter()
            try:
                formula = algo.solve(number, should_cancel=stale)
                self._results.put((req_id, formula, None, (time.perf_counter() - t0) * 1000))
            except SolveCancelled:
                continue
            except Exception as exc:
                self._results.put((req_id, None, str(exc), 0.0))

    def _submit(self, number):
        self._req_id += 1
        with self._cv:
            self._req = (self._req_id, number)
            self._cv.notify()
        if self._busy_job is None:
            self._busy_job = self.root.after(160, self._show_busy)
        if self._poll_job is None:
            self._poll_job = self.root.after(8, self._poll_results)

    def _cancel_pending(self):
        self._req_id += 1
        self._done_id = self._req_id
        with self._cv:
            self._req = None
        if self._busy_job is not None:
            self.root.after_cancel(self._busy_job)
            self._busy_job = None

    def _show_busy(self):
        self._busy_job = None
        if self._done_id != self._req_id:
            self._set_status("Searching…", CLR_MUTED, remember=False)

    def _poll_results(self):
        self._poll_job = None
        result = None
        while True:
            try:
                item = self._results.get_nowait()
            except queue.Empty:
                break
            if item[0] == self._req_id:
                result = item
        if result is not None:
            req_id, formula, error, ms = result
            self._done_id = req_id
            if self._busy_job is not None:
                self.root.after_cancel(self._busy_job)
                self._busy_job = None
            if error:
                self.current_formula = ""
                self._show_formula("")
                self._set_status(error, CLR_ACCENT)
            else:
                self.current_formula = formula
                self._animate_formula(formula)
                took = f"{ms:.0f} ms" if ms >= 1 else "<1 ms"
                self._set_status(
                    f"Constructed · {len(formula)} characters · {took}", CLR_ACCENT
                )
        if self._done_id != self._req_id:
            self._poll_job = self.root.after(10, self._poll_results)

    # ------------------------------------------------------------ 输入
    @staticmethod
    def _digits(text):
        return "".join(ch for ch in text if ch.isdigit())

    def handle_input(self, _event=None):
        raw = self._digits(self.entry.get())
        self.eq_target = 90.0 if raw else 0.0
        self._start_eq()
        if self._task:
            self.root.after_cancel(self._task)
        # 求解在后台线程，防抖只需很短，输入几乎实时出结果。
        self._task = self.root.after(35, self.solve_logic)

    def solve_logic(self):
        if self._task:
            self.root.after_cancel(self._task)
            self._task = None

        raw = self._digits(self.entry.get())
        if not raw:
            self._cancel_pending()
            self.current_formula = ""
            self._show_formula("")
            self._set_status("Ready · Enter a number to begin", CLR_MUTED)
            self.eq_target = 0.0
            self._start_eq()
            return
        if len(raw) > 15:
            self._cancel_pending()
            self.current_formula = ""
            self._show_formula("")
            self._set_status("Please enter at most 15 digits.", CLR_ACCENT)
            return
        self._submit(int(raw))

    # ------------------------------------------------------------ 结果显示
    def _stop_typing(self):
        self.type_generation += 1
        if self.typing_task:
            self.root.after_cancel(self.typing_task)
            self.typing_task = None

    def _set_result_text(self, text):
        self._scroll_target = 0.0
        self.res_txt.yview_moveto(0.0)
        self.res_txt.configure(state=tk.NORMAL)
        self.res_txt.delete("1.0", tk.END)
        if text:
            self.res_txt.insert(tk.END, text, "formula")
        self.res_txt.configure(state=tk.DISABLED)

    def _show_formula(self, formula):
        self._stop_typing()
        self._set_result_text(formula)

    def _animate_formula(self, formula):
        """短表达式直接显示；长表达式约 10 帧内显影完毕，不拖慢连续输入。"""
        self._stop_typing()
        if len(formula) <= 16:
            self._set_result_text(formula)
            return
        generation = self.type_generation
        self._set_result_text("")
        step = -(-len(formula) // 10)

        def reveal(index=0):
            if generation != self.type_generation:
                return
            end = min(len(formula), index + step)
            self.res_txt.configure(state=tk.NORMAL)
            self.res_txt.insert(tk.END, formula[index:end], "formula")
            self.res_txt.configure(state=tk.DISABLED)
            if end < len(formula):
                self.typing_task = self.root.after(14, lambda: reveal(end))
            else:
                self.typing_task = None

        reveal()

    # ------------------------------------------------------------ 等号动效
    def _start_eq(self):
        if self.anim_task is None:
            self._animate_eq()

    def _animate_eq(self):
        # 平滑缓动；到位后停止调度，空闲时不再占用 CPU。
        delta = self.eq_target - self.eq_angle
        if abs(delta) > 0.12:
            self.eq_angle += delta * 0.20
        else:
            self.eq_angle = self.eq_target

        angle = math.radians(self.eq_angle)
        cx, cy = 36, 21
        half = 12
        offset = 4.5
        cos_a, sin_a = math.cos(angle), math.sin(angle)

        def line_points(side):
            ox, oy = -side * offset * sin_a, side * offset * cos_a
            dx, dy = half * cos_a, half * sin_a
            return (cx - dx + ox, cy - dy + oy, cx + dx + ox, cy + dy + oy)

        self.eq_canvas.coords(self.eq_line_a, *line_points(-1))
        self.eq_canvas.coords(self.eq_line_b, *line_points(1))
        if self.eq_angle != self.eq_target:
            self.anim_task = self.root.after(16, self._animate_eq)
        else:
            self.anim_task = None

    # ------------------------------------------------------------ 复制
    def copy_formula(self, _event=None):
        if not self.current_formula:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.current_formula)
        self._set_status("Copied to clipboard ✓", CLR_ACCENT, remember=False)
        self.copy_button.configure(text="Copied! ✓", fg=CLR_ACCENT)
        if getattr(self, "_copy_reset_job", None):
            self.root.after_cancel(self._copy_reset_job)
        self._copy_reset_job = self.root.after(1500, self._reset_copy_feedback)

    def _reset_copy_feedback(self):
        self._copy_reset_job = None
        self.copy_button.configure(text="Copy  ↗", fg=CLR_PRIME)
        text, fg = self._status_state
        self.status.configure(text=text, fg=fg)


if __name__ == "__main__":
    app_root = tk.Tk()
    FrierenGrimoire(app_root)
    app_root.mainloop()
