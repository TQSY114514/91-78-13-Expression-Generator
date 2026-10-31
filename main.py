import tkinter as tk
from tkinter import font as tkfont
import itertools
import sys

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

        self.bind("<KeyPress>", self._on_key)
        self.bind("<Button-1>", self._on_click)
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

    def _redraw(self):
        # 显式调用 Canvas.delete，避免与输入框兼容接口 delete() 冲突。
        tk.Canvas.delete(self, "all")
        height = max(1, self.winfo_height())
        baseline = height / 2
        text_x = 12 - self.scroll_x

        start, end = self._selection()
        if start != end:
            sx = text_x + self.font.measure(self.value[:start])
            ex = text_x + self.font.measure(self.value[:end])
            self.create_rectangle(
                sx, 8, ex, height - 8, fill=self.select_bg, outline=""
            )
        self.create_text(
            text_x, baseline, anchor="w", text=self.value,
            font=self.font, fill=self.fg_color
        )
        if start != end:
            sx = text_x + self.font.measure(self.value[:start])
            selected = self.value[start:end]
            self.create_text(
                sx, baseline, anchor="w", text=selected,
                font=self.font, fill=self.select_fg
            )

        if self.focused:
            caret_color = self._mix_color(
                self.bg_color, self.caret_color, 0.25 + 0.75 * getattr(self, 'blink_phase_value', 0.0)
            )
            cx = self.visual_x - self.scroll_x
            self.create_line(
                cx, baseline - 15, cx, baseline + 15,
                fill=caret_color, width=1.6
            )

    def _animate(self):
        # 约 60fps 的缓动：位置追随目标，闪烁使用连续正弦曲线。
        import math
        target_x = 12 + self.font.measure(self.value[:self.caret])
        self.visual_x += (target_x - self.visual_x) * 0.32
        self.scroll_x += (self.target_scroll_x - self.scroll_x) * 0.24
        if abs(target_x - self.visual_x) < 0.15:
            self.visual_x = target_x
        if abs(self.target_scroll_x - self.scroll_x) < 0.15:
            self.scroll_x = self.target_scroll_x

        if self.focused:
            self.blink_phase = (self.blink_phase + 0.055) % (2 * math.pi)
            # 从低亮度平滑过渡到高亮度，再平滑淡出。
            self.blink_phase_value = 0.5 - 0.5 * math.cos(self.blink_phase)
            self.blink_phase = self.blink_phase
            self._redraw()
        else:
            self.blink_phase_value = 0.0
            self._redraw()
        self._animation_job = self.after(16, self._animate)


class _ProofExpr:
    """不可变的四则运算表达式树节点。"""
    __slots__ = ("value", "op", "left", "right", "literal", "_rendered")

    PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2}

    def __init__(self, value, op=None, left=None, right=None, literal=None):
        self.value = int(value)
        self.op = op
        self.left = left
        self.right = right
        self.literal = literal
        self._rendered = None

    @classmethod
    def atom(cls, literal):
        return cls(int(literal), literal=str(literal))

    @classmethod
    def combine(cls, op, left, right):
        a, b = left.value, right.value
        if op == "+":
            value = a + b
        elif op == "-":
            value = a - b
        elif op == "*":
            value = a * b
        elif op == "/":
            if b == 0 or a % b != 0:
                return None
            value = a // b
        else:
            raise ValueError(f"Unknown operator: {op}")
        return cls(value, op=op, left=left, right=right)

    def render(self, parent_op=None, side=None):
        if self._rendered is None:
            if self.op is None:
                self._rendered = self.literal
            else:
                self._rendered = (
                    self.left.render(self.op, "left")
                    + self.op
                    + self.right.render(self.op, "right")
                )
        text = self._rendered
        if parent_op is None or self.op is None:
            return text

        own_precedence = self.PRECEDENCE[self.op]
        parent_precedence = self.PRECEDENCE[parent_op]
        needs_parentheses = own_precedence < parent_precedence

        if own_precedence == parent_precedence and side == "right":
            # 同优先级时，只有这些右子树不能直接按左结合方式展开。
            if parent_op == "+" and self.op == "-":
                needs_parentheses = True
            elif parent_op == "-" and self.op in ("+", "-"):
                needs_parentheses = True
            elif parent_op == "*" and self.op == "/":
                needs_parentheses = True
            elif parent_op == "/" and self.op in ("*", "/"):
                needs_parentheses = True

        return f"({text})" if needs_parentheses else text

    def score(self):
        text = self.render()
        return (
            len(text),
            text.count("("),
            self.operator_count(),
            text,
        )

    def operator_count(self):
        if self.op is None:
            return 0
        return 1 + self.left.operator_count() + self.right.operator_count()

    def digit_stream(self):
        if self.op is None:
            return self.literal
        return self.left.digit_stream() + self.right.digit_stream()


class FinalArtAlgo:
    """
    用 91、78、13 构造非负整数表达式。

    核心改动：
    1. 用表达式树计算和保存候选，不在递归过程中拼接括号。
    2. 用区间 DP 穷举最多 5 个原子的所有二叉四则表达式。
    3. 每个数值按根运算符分别保留最优表达式，避免上下文括号成本被错误剪枝。
    4. 对更大的目标，再用多基底商/余数分解，并比较全部候选。
    5. 最终统一按运算优先级和左右结合性生成最少必要括号。

    “最多 5 个原子”的 DP 部分是精确穷举；更大数字的递归分解是启发式搜索，
    不宣称对任意大整数都能保证全局最短。
    """

    def __init__(self):
        self.atoms = ("91", "78", "13")
        self.atom_values = {int(x): x for x in self.atoms}
        self.max_exact_atoms = 5
        self.value_limit = 10**18
        self.exact_cache = self._build_exact_cache()
        self._augment_small_number_cache()
        self.memo = {}

    @staticmethod
    def _state_key(expr):
        # 同一数值但不同根运算符，在父节点中可能需要不同括号，不能互相覆盖。
        return expr.op

    @staticmethod
    def _keep_best(bucket, expr):
        old = bucket.get(expr.op)
        if old is None or expr.score() < old.score():
            bucket[expr.op] = expr

    def _build_exact_cache(self):
        """对 1~5 个原子的每一种有序序列做区间 DP。"""
        cache = {}
        for count in range(1, self.max_exact_atoms + 1):
            for sequence in itertools.product(self.atoms, repeat=count):
                dp = {}
                # 任意连续原子段也可以直接拼成一个数字，例如 91|78 -> 9178。
                for start in range(count):
                    for end in range(start + 1, count + 1):
                        literal = "".join(sequence[start:end])
                        dp[(start, end)] = {None: _ProofExpr.atom(literal)}

                for span in range(2, count + 1):
                    for start in range(count - span + 1):
                        end = start + span
                        literal = "".join(sequence[start:end])
                        literal_expr = _ProofExpr.atom(literal)
                        out = {(literal_expr.value, None): literal_expr}
                        for split in range(start + 1, end):
                            left_states = dp[(start, split)].values()
                            right_states = dp[(split, end)].values()
                            for left in left_states:
                                for right in right_states:
                                    for op in ("+", "-", "*", "/"):
                                        candidate = _ProofExpr.combine(op, left, right)
                                        if candidate is None:
                                            continue
                                        if abs(candidate.value) > self.value_limit:
                                            continue
                                        state_key = (candidate.value, candidate.op)
                                        old = out.get(state_key)
                                        if old is None or candidate.score() < old.score():
                                            out[state_key] = candidate
                        dp[(start, end)] = out

                for expr in dp[(0, count)].values():
                    bucket = cache.setdefault(expr.value, {})
                    self._keep_best(bucket, expr)
        return cache

    def _augment_small_number_cache(self):
        """用 1、6、7 的精确表达式补齐 0~90，避免小数值递归互相绕圈。"""
        a91 = _ProofExpr.atom("91")
        a78 = _ProofExpr.atom("78")
        a13 = _ProofExpr.atom("13")
        one = _ProofExpr.combine("/", _ProofExpr.combine("-", a91, a78), a13)
        six = _ProofExpr.combine("/", a78, a13)
        seven = _ProofExpr.combine("/", a91, a13)
        zero = _ProofExpr.combine(
            "-", _ProofExpr.combine("-", a91, a78), a13
        )
        units = (one, six, seven)
        best = {0: {zero.op: zero}}

        for number in range(1, 91):
            bucket = dict(self.exact_cache.get(number, {}))
            for unit in units:
                previous_number = number - unit.value
                if previous_number < 0 or previous_number not in best:
                    continue
                for previous in best[previous_number].values():
                    candidate = unit if previous_number == 0 else _ProofExpr.combine(
                        "+", previous, unit
                    )
                    if candidate is not None and candidate.value == number:
                        self._keep_best(bucket, candidate)
            if bucket:
                best[number] = bucket
                self.exact_cache[number] = bucket

    def _candidates_for(self, n):
        n = int(n)
        if n < 0:
            raise ValueError("Only non-negative integers are supported")

        if n in self.atom_values:
            return {None: _ProofExpr.atom(self.atom_values[n])}
        if n in self.memo:
            return self.memo[n]
        if n in self.exact_cache:
            self.memo[n] = self.exact_cache[n]
            return self.memo[n]

        candidates = {}
        for base_text in self.atoms:
            base = int(base_text)
            base_expr = _ProofExpr.atom(base_text)
            q, r = divmod(n, base)

            # 向下取整：n = base*q + r
            if q > 0:
                for q_expr in self._candidates_for(q).values():
                    product = _ProofExpr.combine("*", base_expr, q_expr)
                    if product is None:
                        continue
                    if r == 0:
                        self._keep_best(candidates, product)
                    else:
                        for r_expr in self._candidates_for(r).values():
                            candidate = _ProofExpr.combine("+", product, r_expr)
                            if candidate is not None and candidate.value == n:
                                self._keep_best(candidates, candidate)

            # 向上取整：n = base*q_up - gap
            q_up = q + (1 if r else 0)
            gap = q_up * base - n
            if gap > 0:
                for q_expr in self._candidates_for(q_up).values():
                    product = _ProofExpr.combine("*", base_expr, q_expr)
                    if product is None:
                        continue
                    for gap_expr in self._candidates_for(gap).values():
                        candidate = _ProofExpr.combine("-", product, gap_expr)
                        if candidate is not None and candidate.value == n:
                            self._keep_best(candidates, candidate)

        if not candidates:
            raise ValueError(f"无法构造数字 {n} 的表达式")
        self.memo[n] = candidates
        return candidates

    def solve(self, n):
        n = int(n)
        if n < 0:
            raise ValueError("请输入非负整数")
        candidates = self._candidates_for(n)
        best = min(candidates.values(), key=lambda expr: expr.score())
        result = best.render()

        # 最终安全校验：值正确，且数字串可完整拆分为给定原子。
        if best.value != n or not self._is_atomic_sequence(result):
            raise ValueError("内部校验失败：生成的表达式不符合原子规则")
        return result

    def _is_atomic_sequence(self, expr):
        digits = "".join(ch for ch in expr if ch.isdigit())
        if not digits:
            return False
        # 原子均为两位数，按顺序每两位验证即可。
        if len(digits) % 2:
            return False
        return all(digits[i:i + 2] in self.atoms for i in range(0, len(digits), 2))

    @staticmethod
    def _evaluate(expr):
        """仅用于测试/校验内部表达式；除法节点必须得到整数。"""
        import ast
        from fractions import Fraction
        tree = ast.parse(expr, mode="eval")

        def visit(node):
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.Constant) and type(node.value) is int:
                return Fraction(node.value)
            if isinstance(node, ast.BinOp):
                a, b = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add):
                    return a + b
                if isinstance(node.op, ast.Sub):
                    return a - b
                if isinstance(node.op, ast.Mult):
                    return a * b
                if isinstance(node.op, ast.Div):
                    if b == 0:
                        raise ValueError("division by zero")
                    value = a / b
                    if value.denominator != 1:
                        raise ValueError("non-integer division")
                    return value
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
        self.algo = FinalArtAlgo()
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
            select_bg=CLR_ACCENT, select_fg=CLR_BG, height=58
        )
        self.entry.pack(fill=tk.X, padx=16, pady=12)
        self.entry.bind("<<InputChanged>>", self.handle_input)
        self.entry.bind("<<Submit>>", lambda _event: self.solve_logic())
        self.entry.focus_set()

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

    def handle_input(self, _event=None):
        raw = "".join(ch for ch in self.entry.get() if ch.isdigit())
        self.eq_target = 90.0 if raw else 0.0
        if self._task:
            self.root.after_cancel(self._task)
        self._task = self.root.after(110, self.solve_logic)

    def solve_logic(self):
        if self._task:
            self.root.after_cancel(self._task)
            self._task = None
        if self.typing_task:
            self.root.after_cancel(self.typing_task)
            self.typing_task = None

        raw = "".join(ch for ch in self.entry.get() if ch.isdigit())
        if not raw:
            self.current_formula = ""
            self._show_formula("")
            self.status.configure(text="Ready · Enter a number to begin", fg=CLR_MUTED)
            self.eq_target = 0.0
            return

        try:
            if len(raw) > 15:
                raise ValueError("Please enter at most 15 digits.")
            number = int(raw)
            formula = self.algo.solve(number)
            self.current_formula = formula
            self._animate_formula(formula)
            self.status.configure(
                text=f"Constructed · {len(formula)} characters",
                fg=CLR_ACCENT
            )
        except Exception as exc:
            self.current_formula = ""
            self._show_formula("")
            self.status.configure(text=str(exc), fg=CLR_ACCENT)

    def _show_formula(self, formula):
        self._scroll_target = 0.0
        self.res_txt.yview_moveto(0.0)
        self.res_txt.configure(state=tk.NORMAL)
        self.res_txt.delete("1.0", tk.END)
        if formula:
            self.res_txt.insert(tk.END, formula, "formula")
        self.res_txt.configure(state=tk.DISABLED)

    def _animate_formula(self, formula):
        """逐段显影：短表达式更快，长表达式按块出现，避免动画拖沓。"""
        self._scroll_target = 0.0
        self.res_txt.yview_moveto(0.0)
        self.type_generation += 1
        generation = self.type_generation
        self.res_txt.configure(state=tk.NORMAL)
        self.res_txt.delete("1.0", tk.END)
        self.res_txt.configure(state=tk.DISABLED)
        step = max(1, min(5, len(formula) // 55 + 1))

        def reveal(index=0):
            if generation != self.type_generation:
                return
            end = min(len(formula), index + step)
            self.res_txt.configure(state=tk.NORMAL)
            self.res_txt.insert(tk.END, formula[index:end], "formula")
            self.res_txt.configure(state=tk.DISABLED)
            if end < len(formula):
                self.typing_task = self.root.after(12, lambda: reveal(end))
            else:
                self.typing_task = None

        reveal()

    def _animate_eq(self):
        # 平滑缓动，不做窗口尺寸/位置回弹。
        delta = self.eq_target - self.eq_angle
        if abs(delta) > 0.12:
            self.eq_angle += delta * 0.20
        else:
            self.eq_angle = self.eq_target

        angle = self.eq_angle * 3.141592653589793 / 180.0
        cx, cy = 36, 21
        half = 12
        offset = 4.5
        cos_a, sin_a = __import__("math").cos(angle), __import__("math").sin(angle)

        def line_points(side):
            ox, oy = -side * offset * sin_a, side * offset * cos_a
            dx, dy = half * cos_a, half * sin_a
            return (cx - dx + ox, cy - dy + oy, cx + dx + ox, cy + dy + oy)

        self.eq_canvas.coords(self.eq_line_a, *line_points(-1))
        self.eq_canvas.coords(self.eq_line_b, *line_points(1))
        self.anim_task = self.root.after(16, self._animate_eq)

    def copy_formula(self, _event=None):
        if not self.current_formula:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.current_formula)
        self.status.configure(text="Copied to clipboard", fg=CLR_ACCENT)


if __name__ == "__main__":
    app_root = tk.Tk()
    FrierenGrimoire(app_root)
    app_root.mainloop()
