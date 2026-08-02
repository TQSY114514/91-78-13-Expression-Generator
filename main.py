import tkinter as tk
import math
import random
from functools import lru_cache
try:
    from PIL import Image, ImageTk
except ImportError:
    pass
import sys

# ====== 魔法美学配色 ======
CLR_BG = "#F2F0E9"
CLR_PRIME = "#2C3E50"
CLR_ACCENT = "#7F8C8D"
CLR_GOLD = "#D4AF37"


class FinalArtAlgo:
    def __init__(self):
        self.memo = {}
        self.atoms = ["91", "78", "13"]

    def is_valid_atomic_sequence(self, raw_str):
        """
        核心规则优化：视觉序列校验！
        提取算式中所有的纯数字部分拼成一个长字符串，检查它是否能被 91, 78, 13 完整拼出。
        例如：'9178' -> True  (由 91 + 78 拼成，允许 917+8)
              '7891' -> True  (由 78 + 91 拼成，允许 789+1)
              '9173' -> False (73 无效，拒绝 917+3)
        """
        digits_only = "".join(filter(str.isdigit, raw_str))
        if not digits_only:
            return False

        # 类似“贪吃蛇”匹配：从前向后尝试用 91, 78, 13 消除
        temp = digits_only
        while temp:
            matched = False
            for atom in self.atoms:
                if temp.startswith(atom):
                    temp = temp[len(atom):]
                    matched = True
                    break
            if not matched:
                return False  # 有无法匹配的残渣数字，判定为非法
        return True

    def wrap(self, text, level):
        """严格括号层级：( ) -> [ ] -> { }"""
        brackets = [("(", ")"), ("[", "]"), ("{", "}")]
        b_o, b_c = brackets[level % 3]
        return f"{b_o}{text}{b_c}"

    def is_complete(self, s):
        """核心防御：完整性检查 + 视觉规范检查"""
        if not s or len(s) < 2: 
            return False
        # 禁止运算符在开头或结尾
        if s[-1] in "+-*/" or s[0] in "+*/": 
            return False

        # 确保括号成对
        counts = [s.count(b) for b in "()[]{}"]
        if counts[0] != counts[1] or counts[2] != counts[3] or counts[4] != counts[5]:
            return False

        # 严格执行 91, 78, 13 拼接规则校验
        if not self.is_valid_atomic_sequence(s):
            return False

        return True

    @lru_cache(maxsize=4096)
    def solve(self, n, level=0):
        n = int(n)
        state_key = (n, level)
        if state_key in self.memo: 
            return self.memo[state_key]

        # 1. 基础出口
        if str(n) in self.atoms: 
            return str(n)
        if n == 1: 
            return "((91-78)/13)"
        if n == 0: 
            return "(91-78-13)"

        # --- 策略 A: 视觉拼凑（支持 917+8, 789+1 等合理拆分） ---
        for count in [1, 2, 3]:
            for _ in range(80):
                # 随机生成原子池
                pool = "".join(random.choices(self.atoms, k=count))
                for i in range(1, len(pool)):
                    s1, s2 = pool[:i], pool[i:]
                    try:
                        a, b = int(s1), int(s2)
                        res_body = ""
                        if a + b == n: res_body = f"{s1}+{s2}"
                        elif a - b == n: res_body = f"{s1}-{s2}"
                        elif a * b == n: res_body = f"{s1}*{s2}"
                        elif b != 0 and a % b == 0 and a // b == n: res_body = f"{s1}/{s2}"

                        if res_body:
                            final = self.wrap(res_body, level)
                            if self.is_complete(final):
                                self.memo[state_key] = final
                                return final
                    except: 
                        continue

        # --- 策略 B: 数学降维递归 ---
        bases = [91, 78, 13]
        random.shuffle(bases)
        for base in bases:
            if n > base:
                m, r = n // base, n % base
                m_expr = self.solve(m, level + 1)
                if not self.is_complete(m_expr): 
                    continue

                if r == 0:
                    final = self.wrap(f"{base}*{m_expr}", level)
                else:
                    r_expr = self.solve(r, level + 1)
                    if not self.is_complete(r_expr): 
                        continue
                    final = self.wrap(f"{base}*{m_expr}+{r_expr}", level)

                if self.is_complete(final):
                    self.memo[state_key] = final
                    return final

        # --- 策略 C: 终极保底 ---
        p_expr = self.solve(n - 1, level + 1)
        o_expr = self.solve(1, level + 1)
        if not self.is_complete(p_expr): 
            p_expr = "91"
            
        final = self.wrap(f"{p_expr}+{o_expr}", level)
        self.memo[state_key] = final
        return final


class FrierenGrimoire:
    def __init__(self, root):
        self.root = root
        self.root.title("Numeric Grimoire")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=CLR_BG)

        self.algo = FinalArtAlgo()
        self.ideal_size = [640, 520]
        self.target_geom = [640, 520, 0, 0]
        self.eq_angle, self.eq_target = 0.0, 0.0
        self.title_size, self.title_target = 26.0, 26.0

        self.is_dragging = False
        self.drag_data = {"x": 0, "y": 0}
        self.typing_task = None
        self._task = None

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        sx, sy = (sw - 640) // 2, (sh - 520) // 2
        self.target_geom[2], self.target_geom[3] = sx, sy
        self.root.geometry(f"640x520+{sx}+{sy}")

        self.setup_ui()
        self.bind_magic_events()
        self.update_loop()

    def setup_ui(self):
        self.title_label = tk.Label(self.root, text="N U M E R I C    P R O O F",
                                    font=("Georgia", 26, "italic"),
                                    fg=CLR_PRIME, bg=CLR_BG)
        self.title_label.pack(pady=(70, 10))

        line_container = tk.Frame(self.root, bg=CLR_BG)
        line_container.pack(pady=(0, 20))
        self.line_deco = tk.Frame(line_container, height=1, bg=CLR_GOLD, width=320)
        self.line_deco.pack()

        self.entry = tk.Entry(self.root, font=("Garamond", 34), justify="center",
                              bd=0, bg=CLR_BG, fg=CLR_PRIME,
                              highlightthickness=0, insertontime=0, insertwidth=0, width=25)
        self.entry.pack(pady=10, padx=100)
        self.entry.focus_set()

        self.canvas = tk.Canvas(self.root, width=120, height=80, bg=CLR_BG, highlightthickness=0)
        self.canvas.pack(pady=10)
        line_opt = {"fill": CLR_PRIME, "width": 2, "capstyle": tk.ROUND, "smooth": True}
        self.l1 = self.canvas.create_line(0, 0, 0, 0, **line_opt)
        self.l2 = self.canvas.create_line(0, 0, 0, 0, **line_opt)

        self.res_txt = tk.Text(self.root, font=("Georgia", 16, "italic"), fg=CLR_BG,
                               bd=0, bg=CLR_BG, highlightthickness=0,
                               state=tk.DISABLED, spacing1=15, spacing3=15,
                               padx=60, wrap=tk.WORD)
        self.res_txt.pack(expand=True, fill=tk.BOTH)
        self.res_txt.tag_configure("center", justify='center')

    def bind_magic_events(self):
        self.root.bind("<Button-1>", self.start_drag)
        self.root.bind("<B1-Motion>", self.do_drag)
        self.root.bind("<ButtonRelease-1>", self.stop_drag)
        self.entry.bind('<KeyRelease>', self.handle_input)
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

    def start_drag(self, event):
        self.is_dragging = True
        self.drag_data["x"], self.drag_data["y"] = event.x, event.y

    def do_drag(self, event):
        if self.is_dragging:
            nx = self.root.winfo_x() + (event.x - self.drag_data["x"])
            ny = self.root.winfo_y() + (event.y - self.drag_data["y"])
            self.root.geometry(f"+{nx}+{ny}")
            self.target_geom[2], self.target_geom[3] = nx, ny

    def stop_drag(self, _):
        self.is_dragging = False
        self.adapt_env()

    def handle_input(self, _):
        val = self.entry.get().strip()
        self.eq_target = 90.0 if val else 0.0
        self.title_target = 11.0 if val else 26.0
        if self._task: self.root.after_cancel(self._task)
        self._task = self.root.after(120, self.solve_logic)

    def solve_logic(self):
        raw = self.entry.get().strip()
        if self.typing_task: self.root.after_cancel(self.typing_task)
        self.res_txt.configure(state=tk.NORMAL)
        self.res_txt.delete(1.0, tk.END)
        if not raw:
            self.ideal_size = [640, 520]
            self.adapt_env()
            return
        try:
            num = int("".join(filter(str.isdigit, raw)) or 0)
            formula = self.algo.solve(num)
            c_len = len(formula)
            h = 520 + (c_len // 40) * 35
            w = 640 + (c_len // 10) if c_len > 120 else 640
            self.ideal_size = [min(w, 1100), min(h, 900)]
            self.adapt_env()
            self.misty_type(formula, 0)
        except: pass

    def misty_type(self, text, idx):
        self.res_txt.configure(state=tk.NORMAL)
        self.res_txt.delete(1.0, tk.END)
        self.res_txt.insert(tk.END, text[:idx], "center")
        self.res_txt.tag_add("center", "1.0", tk.END)
        progress = idx / len(text) if len(text) > 0 else 1
        self.res_txt.configure(fg=self.lerp(CLR_BG, CLR_PRIME, math.pow(progress, 0.4)), state=tk.DISABLED)
        if idx <= len(text) + 2:
            self.typing_task = self.root.after(16, lambda: self.misty_type(text, idx + 2))

    @staticmethod
    def lerp(c1, c2, t):
        t = max(0, min(1, t))
        r1, g1, b1 = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
        r2, g2, b2 = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
        return f'#{int(r1 + (r2 - r1) * t):02x}{int(g1 + (g2 - g1) * t):02x}{int(b1 + (b2 - b1) * t):02x}'

    def adapt_env(self):
        """复杂的屏幕边界感应与回弹算法"""
        if self.is_dragging: return
        try:
            import ctypes
            from ctypes import wintypes
            cx, cy = self.root.winfo_x(), self.root.winfo_y()
            cw, ch = self.root.winfo_width(), self.root.winfo_height()
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            iw, ih = self.ideal_size
            MIN_W, MIN_H, MAX_W, MAX_H, M = 480, 380, 1100, 900, 10
            
            try:
                SPI_GETWORKAREA = 0x0030
                rect = wintypes.RECT()
                ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
                L, T, R, B = rect.left + M, rect.top + M, rect.right - M, rect.bottom - M
            except:
                L, T, R, B = M, M, sw - M, sh - 40 - M
            
            desired_w, desired_h = max(MIN_W, min(iw, MAX_W)), max(MIN_H, min(ih, MAX_H))
            
            max_w_screen = R - L
            if desired_w > max_w_screen: desired_w = max(MIN_W, max_w_screen)
            
            ratio = desired_w / max(1, iw)
            if ratio < 1.0:
                desired_h = int(desired_h * (1.0 / max(0.25, ratio)) ** 1.25)
                desired_h = max(MIN_H, min(desired_h, MAX_H))
            
            EDGE = 30
            near_left, near_top = (cx - L) < EDGE, (cy - T) < EDGE
            near_right, near_bottom = (R - (cx + cw)) < EDGE, (B - (cy + ch)) < EDGE
            
            tx, ty, fw, fh = cx, cy, min(desired_w, R - L), min(desired_h, B - T)
            
            if tx + fw > R: fw = max(MIN_W, R - tx)
            if ty + fh > B: fh = max(MIN_H, B - ty)
            
            if near_left and not near_right:
                right_edge = cx + cw
                tx = right_edge - fw
                if tx < L: tx = L; fw = max(MIN_W, right_edge - tx)
            if near_top and not near_bottom:
                bottom_edge = cy + ch
                ty = bottom_edge - fh
                if ty < T: ty = T; fh = max(MIN_H, bottom_edge - ty)
                
            if tx + fw > R: tx = R - fw
            if ty + fh > B: ty = B - fh
            if tx < L: tx = L
            if ty < T: ty = T
            
            self.target_geom = [int(fw), int(fh), int(tx), int(ty)]
        except:
            pass

    def update_loop(self):
        if not self.is_dragging:
            cw, ch, cx, cy = self.root.winfo_width(), self.root.winfo_height(), self.root.winfo_x(), self.root.winfo_y()
            tw, th, tx, ty = self.target_geom
            k = 0.16
            if any(abs(a - b) > 0.5 for a, b in [(cw, tw), (ch, th), (cx, tx), (cy, ty)]):
                nw, nh = cw + (tw - cw) * k, ch + (th - ch) * k
                nx, ny = cx + (tx - cx) * k, cy + (ty - cy) * k
                self.root.geometry(f"{int(nw)}x{int(nh)}+{int(nx)}+{int(ny)}")

        if abs(self.title_size - self.title_target) > 0.1:
            self.title_size += (self.title_target - self.title_size) * 0.12
            self.title_label.configure(font=("Georgia", int(self.title_size), "italic"))
            
        if abs(self.eq_angle - self.eq_target) > 0.1:
            self.eq_angle += (self.eq_target - self.eq_angle) * 0.2
        self.draw_eq(self.eq_angle)
        
        self.root.after(16, self.update_loop)

    def draw_eq(self, angle):
        rad = math.radians(angle)
        cx, cy, d = 60, 40, 16 * (1.0 - (angle / 90.0) * 0.1)
        cosa, sina = math.cos(rad), math.sin(rad)
        def pts(o): return (cx - d * cosa - o * sina, cy - d * sina + o * cosa, cx + d * cosa - o * sina,
                            cy + d * sina + o * cosa)
        self.canvas.coords(self.l1, *pts(-6))
        self.canvas.coords(self.l2, *pts(6))


if __name__ == "__main__":
    app_root = tk.Tk()
    FrierenGrimoire(app_root)
    app_root.mainloop()
