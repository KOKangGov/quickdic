"""
QuickDic — 작은 플로팅 사전

  · 화면 위에 작은 사전 창을 띄워 두고
  · 다른 프로그램에서 단어를 드래그한 뒤 Alt+Q 를 누르면 바로 찾아 줍니다.
  · 위키낱말사전(Wiktionary) 기반 오프라인 사전, 주 1회 자동 업데이트.
"""

from __future__ import annotations

import os
import queue
import re
import sys
import threading
import tkinter as tk
import urllib.parse
from tkinter import filedialog, font as tkfont, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import updater  # noqa: E402
import winsys  # noqa: E402
from dictdb import Dictionary, Doc, Result, clean_query, is_korean  # noqa: E402

TITLE = "QuickDic"

C = {
    "bg": "#F6F5F1", "panel": "#FFFFFF", "line": "#DEDCD5", "text": "#1E2226",
    "ko": "#16191C", "en": "#363C44", "dim": "#8A8F97", "accent": "#2459C2",
    "accent_dk": "#1B4596", "tag": "#AE5410", "pos": "#1D4E9E", "ex": "#22272D",
    "tr": "#5A6370", "note": "#8A6A14", "chip": "#EBE9E3", "hover": "#E3E8F3",
    "on": "#DCE6FA", "star": "#E0A100",
}


def pick_font(root, *names, default="TkDefaultFont"):
    fams = set(tkfont.families(root))
    for n in names:
        if n in fams:
            return n
    return tkfont.nametofont(default).actual("family")


# ====================================================================== 작은 위젯


class FlatButton(tk.Label):
    """테두리 없는 납작한 버튼 (마우스 올리면 색 바뀜)"""

    def __init__(self, master, text, command, *, bg=None, fg=None, hover=None, font=None, padx=7, pady=3, tip=None):
        self._bg = bg or C["bg"]
        self._hover = hover or C["hover"]
        super().__init__(master, text=text, bg=self._bg, fg=fg or C["text"], font=font,
                         padx=padx, pady=pady, cursor="hand2")
        self.command = command
        self.active = False
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self.config(bg=C["on"] if self.active else self._bg))
        if tip:
            Tooltip(self, tip)

    def set_active(self, on: bool):
        self.active = on
        self.config(bg=C["on"] if on else self._bg)


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _=None):
        if self.tip:
            return
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)
        tw.geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, bg="#2B2F35", fg="white", padx=6, pady=2,
                 font=(None, 9)).pack()

    def hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ====================================================================== 메인 앱


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = config.Settings()
        self.history = config.History()
        self.bookmarks = config.Bookmarks()
        self.q: queue.Queue = queue.Queue()
        self.dict: Dictionary | None = None
        self.result: Result | None = None
        self.links: dict[str, str] = {}
        self.hotkey: winsys.HotkeyListener | None = None
        self._geom_job = None
        self._sugg_job = None
        self._collapse_job = None
        self.app_update_url = ""

        self._init_fonts()
        self._build_ui()
        self._apply_window_settings()
        self._open_db()
        self._start_hotkey()
        self.updater = updater.Updater(self.settings, lambda k, v=None: self.q.put((k, v)))
        self.root.after(60, self._poll)
        self.root.after(1500, self._maybe_update)
        self.root.after(8000, self._check_app_update)
        self.root.after(3600 * 1000, self._hourly)

    # ------------------------------------------------------------------ 화면 구성
    def _init_fonts(self):
        base = int(self.settings["font_size"])
        ui = pick_font(self.root, "Malgun Gothic", "맑은 고딕", "Apple SD Gothic Neo", "Noto Sans CJK KR", "Segoe UI")
        ipa = pick_font(self.root, "Segoe UI", "Arial Unicode MS", "DejaVu Sans", ui)
        self.f = {
            "ui": (ui, base - 1), "ui_b": (ui, base - 1, "bold"), "small": (ui, base - 2),
            "entry": (ui, base + 2), "head": (ui, base + 7, "bold"), "ipa": (ipa, base),
            "body": (ui, base), "body_b": (ui, base, "bold"), "en": (ipa, base),
            "sec": (ui, base - 1, "bold"), "brand": (ui, base - 1, "bold"),
        }

    def _build_ui(self):
        r = self.root
        r.title(TITLE)
        r.configure(bg=C["bg"])
        r.minsize(300, 120)
        try:
            r.iconbitmap(config.resource_path("assets/quickdic.ico"))
        except Exception:
            pass
        style = ttk.Style(r)
        style.configure("QD.TNotebook", background=C["bg"], borderwidth=0)
        style.configure("QD.TNotebook.Tab", padding=(14, 4), font=self.f["ui"])
        style.configure("QD.TCheckbutton", background=C["panel"], font=self.f["small"])

        # ── 1. 상단 도구 막대
        bar = tk.Frame(r, bg=C["bg"])
        bar.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(bar, text="QuickDic", bg=C["bg"], fg=C["accent"], font=self.f["brand"]).pack(side="left")
        self.btn_fold = FlatButton(bar, "접기 ▲", self.toggle_collapse, font=self.f["small"], tip="창 접기/펼치기 (Esc)")
        self.btn_fold.pack(side="right")
        FlatButton(bar, "설정", self.open_settings, font=self.f["small"], tip="설정").pack(side="right")
        FlatButton(bar, "단어장", self.open_wordbook, font=self.f["small"], tip="저장한 단어 보기").pack(side="right")
        FlatButton(bar, "웹사전", self.open_web, font=self.f["small"],
                   tip="지금 단어를 포털 사전에서 열기").pack(side="right")
        self.btn_pin = FlatButton(bar, "고정", self.toggle_topmost, font=self.f["small"], tip="항상 위에 표시")
        self.btn_pin.pack(side="right")

        # ── 2. 검색 막대
        sf = tk.Frame(r, bg=C["bg"])
        sf.pack(fill="x", padx=8, pady=(2, 4))
        self.search_frame = sf
        box = tk.Frame(sf, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"],
                       highlightcolor=C["accent"])
        box.pack(side="left", fill="x", expand=True)
        self.entry = tk.Entry(box, font=self.f["entry"], relief="flat", bg=C["panel"], fg=C["text"],
                              insertbackground=C["text"])
        self.entry.pack(side="left", fill="x", expand=True, padx=(8, 2), ipady=4)
        FlatButton(box, "✕", self.clear, bg=C["panel"], fg=C["dim"], font=self.f["ui"], tip="지우기").pack(side="right")
        FlatButton(sf, "검색", lambda: self.search(self.entry_text()), bg=C["accent"], fg="white",
                   hover=C["accent_dk"], font=self.f["ui_b"], padx=12, pady=5).pack(side="left", padx=(6, 0))
        self._placeholder_on = False
        self._set_placeholder()
        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.entry.bind("<FocusOut>", lambda e: (self._set_placeholder(), self._hide_suggest_later()))
        self.entry.bind("<Return>", lambda e: self.search(self.entry_text()))
        self.entry.bind("<KeyRelease>", self._on_type)
        self.entry.bind("<Down>", self._focus_suggest)
        r.bind("<Escape>", lambda e: self._on_escape())
        r.bind("<Control-l>", lambda e: self.focus_entry())
        for i in range(3):
            r.bind(f"<Control-Key-{i+1}>", lambda e, i=i: self.nb.select(i))

        # 자동완성 목록 (검색창 아래에 겹쳐서 표시)
        self.sugg = tk.Listbox(r, font=self.f["body"], activestyle="none", relief="solid", bd=1,
                               highlightthickness=0, selectbackground=C["on"], selectforeground=C["text"])
        self.sugg.bind("<ButtonRelease-1>", lambda e: self._pick_suggest())
        self.sugg.bind("<Return>", lambda e: self._pick_suggest())
        def sugg_escape(_e):
            self._hide_suggest()
            self.focus_entry()
            return "break"
        self.sugg.bind("<Escape>", sugg_escape)
        self.sugg.bind("<FocusOut>", lambda e: self._hide_suggest_later())

        # ── 3. 접히는 본문
        self.body = tk.Frame(r, bg=C["bg"])
        self.body.pack(fill="both", expand=True)

        # 최근 검색 칩
        self.chips = tk.Frame(self.body, bg=C["bg"])
        self.chips.pack(fill="x", padx=8, pady=(0, 4))

        card = tk.Frame(self.body, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"])
        card.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        head = tk.Frame(card, bg=C["panel"])
        head.pack(fill="x", padx=10, pady=(8, 2))
        self.lbl_word = tk.Label(head, text="", bg=C["panel"], fg=C["text"], font=self.f["head"], anchor="w")
        self.lbl_word.pack(side="left")
        self.btn_star = FlatButton(head, "☆", self.toggle_bookmark, bg=C["panel"], fg=C["star"],
                                   font=(self.f["head"][0], self.f["head"][1] - 3), tip="단어장에 저장")
        self.btn_star.pack(side="right")
        self.btn_say = FlatButton(head, "♪ 발음", self.pronounce, bg=C["panel"], fg=C["accent"],
                                  font=self.f["small"], tip="발음 듣기 (Windows 내장 음성)")
        self.btn_say.pack(side="right")
        self.lbl_ipa = tk.Label(card, text="", bg=C["panel"], fg=C["dim"], font=self.f["ipa"], anchor="w")
        self.lbl_ipa.pack(fill="x", padx=11)

        self.nb = ttk.Notebook(card, style="QD.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=4, pady=(4, 4))
        self.tabs = {}
        for key, label in (("meaning", " 뜻 "), ("ety", " 어원 "), ("ex", " 예문 ")):
            frame = tk.Frame(self.nb, bg=C["panel"])
            self.nb.add(frame, text=label)
            if key == "meaning":
                self.var_en = tk.BooleanVar(value=bool(self.settings["show_english"]))
                ttk.Checkbutton(frame, text="영영 정의 함께 보기", variable=self.var_en, style="QD.TCheckbutton",
                                command=self._toggle_english).pack(anchor="e", padx=6, pady=(2, 0))
            self.tabs[key] = self._make_text(frame)

        # ── 4. 상태 표시줄
        st = tk.Frame(self.body, bg=C["bg"])
        st.pack(fill="x", padx=10, pady=(0, 5))
        self.lbl_status = tk.Label(st, text="", bg=C["bg"], fg=C["dim"], font=self.f["small"], anchor="w")
        self.lbl_status.pack(side="left", fill="x", expand=True)
        self.lbl_status.bind("<Button-1>", lambda e: self.app_update_url and winsys.open_url(self.app_update_url))
        self.lbl_hint = tk.Label(st, text="", bg=C["bg"], fg=C["dim"], font=self.f["small"])
        self.lbl_hint.pack(side="right")

        r.protocol("WM_DELETE_WINDOW", self.quit)
        r.bind("<Configure>", self._on_configure)
        r.bind("<FocusOut>", self._on_root_focus_out)

        self._refresh_chips()
        self._show_welcome()

    def _make_text(self, parent) -> tk.Text:
        wrap = tk.Frame(parent, bg=C["panel"])
        wrap.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical")
        t = tk.Text(wrap, wrap="word", relief="flat", bg=C["panel"], fg=C["text"], font=self.f["body"],
                    padx=10, pady=6, spacing1=1, spacing3=2, cursor="arrow", yscrollcommand=sb.set,
                    highlightthickness=0, borderwidth=0)
        sb.config(command=t.yview)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        styles = {
            "pos": dict(font=self.f["body_b"], foreground=C["pos"], spacing1=6),
            "sec": dict(font=self.f["sec"], foreground=C["accent"], spacing1=4),
            "num": dict(foreground=C["dim"]),
            "ko": dict(foreground=C["ko"]),
            "en": dict(foreground=C["en"], font=self.f["en"]),
            "tag": dict(foreground=C["tag"], font=self.f["small"]),
            "dim": dict(foreground=C["dim"], font=self.f["small"]),
            "ex": dict(foreground=C["ex"], font=self.f["en"]),
            "tr": dict(foreground=C["tr"]),
            "note": dict(foreground=C["note"], font=self.f["small"]),
            "h1": dict(font=self.f["body_b"]),
            "link": dict(foreground=C["accent"], underline=True),
            "hang": dict(lmargin1=0, lmargin2=26),
        }
        for k, v in styles.items():
            t.tag_configure(k, **v)
        t.tag_raise("link")
        t.tag_bind("link", "<Enter>", lambda e: t.config(cursor="hand2"))
        t.tag_bind("link", "<Leave>", lambda e: t.config(cursor="arrow"))
        t.tag_bind("link", "<Button-1>", lambda e: self._on_link(t))
        # 결과 안의 아무 단어나 더블클릭하면 그 단어를 찾음
        t.bind("<Double-Button-1>", lambda e: self._on_double_click(t, e))
        t.bind("<Control-c>", lambda e: self._copy_text(t))
        t.config(state="disabled")
        return t

    # ------------------------------------------------------------------ 창 설정
    def _apply_window_settings(self):
        r = self.root
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        geo = self.settings["geometry"] or ""
        ok = False
        m = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", geo)
        if m:
            w, h, x, y = (int(v) for v in m.groups())
            # 모니터 구성이 바뀌어 화면 밖에 있으면 기본 위치로
            ok = -w + 60 < x < sw - 60 and -10 < y < sh - 60 and w >= 280
            if ok:
                r.geometry(f"{w}x{h}+{x}+{y}")
        if not ok:
            w, h = 430, int(self.settings["expanded_height"] or 560)
            r.geometry(f"{w}x{h}+{max(0, sw - w - 40)}+90")
        self.set_topmost(bool(self.settings["topmost"]))
        self.set_opacity(int(self.settings["opacity"]))
        if self.settings["collapsed"]:
            r.after(50, self.collapse)

    def _on_configure(self, e):
        if e.widget is not self.root:
            return
        if self._geom_job:
            self.root.after_cancel(self._geom_job)
        self._geom_job = self.root.after(700, self._save_geometry)

    def _save_geometry(self):
        self._geom_job = None
        if self.root.state() != "normal":
            return
        g = self.root.geometry()
        if self.settings["collapsed"]:
            # 접힌 상태에서는 위치만 저장하고 높이는 펼친 높이 유지
            try:
                size, pos = g.split("+", 1)
                w = size.split("x")[0]
                g = f"{w}x{int(self.settings['expanded_height'])}+{pos}"
            except Exception:
                return
        else:
            self.settings["expanded_height"] = self.root.winfo_height()
        self.settings["geometry"] = g
        self.settings.save()

    def set_topmost(self, on: bool):
        self.settings["topmost"] = on
        self.root.attributes("-topmost", on)
        self.btn_pin.set_active(on)
        self.btn_pin.config(text="고정됨" if on else "고정")

    def toggle_topmost(self):
        self.set_topmost(not self.settings["topmost"])
        self.settings.save()

    def set_opacity(self, pct: int):
        pct = max(50, min(100, int(pct)))
        self.settings["opacity"] = pct
        try:
            self.root.attributes("-alpha", pct / 100)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ 접기/펼치기
    def collapse(self):
        if self.body.winfo_manager():
            if not self.settings["collapsed"]:
                self.settings["expanded_height"] = self.root.winfo_height()
            self.body.pack_forget()
        self._hide_suggest()
        self.settings["collapsed"] = True
        self.btn_fold.config(text="펼치기 ▼")
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_reqheight()
        self.root.geometry(f"{w}x{h}")
        self.settings.save()

    def expand(self):
        if not self.body.winfo_manager():
            self.body.pack(fill="both", expand=True)
        self.settings["collapsed"] = False
        self.btn_fold.config(text="접기 ▲")
        w = self.root.winfo_width()
        h = int(self.settings["expanded_height"] or 560)
        self.root.geometry(f"{w}x{max(h, 260)}")
        self.settings.save()

    def toggle_collapse(self):
        self.expand() if self.settings["collapsed"] else self.collapse()

    def _on_escape(self):
        if self.sugg.winfo_ismapped():
            self._hide_suggest()
        else:
            self.collapse()

    def _on_root_focus_out(self, _e):
        if not self.settings["auto_collapse"]:
            return
        if self._collapse_job:
            self.root.after_cancel(self._collapse_job)

        def check():
            self._collapse_job = None
            if self.root.focus_displayof() is None and not self.settings["collapsed"]:
                self.collapse()
        self._collapse_job = self.root.after(300, check)

    def bring_to_front(self):
        r = self.root
        if r.state() in ("iconic", "withdrawn"):
            r.deiconify()
        if self.settings["collapsed"]:
            self.expand()
        r.lift()
        r.attributes("-topmost", True)
        if not self.settings["topmost"]:
            r.after(300, lambda: r.attributes("-topmost", False))
        r.focus_force()

    # ------------------------------------------------------------------ 검색창
    def _set_placeholder(self):
        if not self.entry.get():
            self._placeholder_on = True
            self.entry.config(fg=C["dim"])
            hk = self.settings["hotkey"]
            self.entry.insert(0, f"단어 입력 · 드래그 후 {hk}")

    def _clear_placeholder(self, _=None):
        if self._placeholder_on:
            self.entry.delete(0, "end")
            self.entry.config(fg=C["text"])
            self._placeholder_on = False

    def entry_text(self) -> str:
        return "" if self._placeholder_on else self.entry.get()

    def set_entry(self, text: str):
        self._clear_placeholder()
        self.entry.delete(0, "end")
        self.entry.insert(0, text)

    def focus_entry(self):
        self._clear_placeholder()
        self.entry.focus_set()
        self.entry.select_range(0, "end")

    def clear(self):
        self.set_entry("")
        self._hide_suggest()
        self.focus_entry()

    # 자동완성
    def _on_type(self, e):
        if e.keysym in ("Return", "Escape", "Down", "Up", "Tab"):
            return
        if self._sugg_job:
            self.root.after_cancel(self._sugg_job)
        self._sugg_job = self.root.after(160, self._update_suggest)

    def _update_suggest(self):
        self._sugg_job = None
        text = clean_query(self.entry_text())
        if not self.dict or len(text) < 2:
            self._hide_suggest()
            return
        try:
            words = self.dict.suggestions(text, limit=8)
        except Exception:
            words = []
        words = [w for w in words if w.lower() != text.lower()][:7]
        if not words:
            self._hide_suggest()
            return
        self.sugg.delete(0, "end")
        for w in words:
            self.sugg.insert("end", "  " + w)
        self.sugg.config(height=len(words))
        x = self.search_frame.winfo_x()
        y = self.search_frame.winfo_y() + self.search_frame.winfo_height()
        self.sugg.place(x=x, y=y, width=self.search_frame.winfo_width())
        self.sugg.lift()

    def _focus_suggest(self, _=None):
        if self.sugg.winfo_ismapped():
            self.sugg.focus_set()
            self.sugg.selection_clear(0, "end")
            self.sugg.selection_set(0)
            self.sugg.activate(0)
        return "break"

    def _pick_suggest(self):
        sel = self.sugg.curselection()
        if sel:
            self.search(self.sugg.get(sel[0]).strip())

    def _hide_suggest(self):
        self.sugg.place_forget()

    def _hide_suggest_later(self):
        def check():
            f = self.root.focus_get()
            if f not in (self.entry, self.sugg):
                self._hide_suggest()
        self.root.after(150, check)

    # ------------------------------------------------------------------ 검색
    def search(self, raw: str, from_hotkey: bool = False):
        q = clean_query(raw or "")
        self._hide_suggest()
        if not q:
            self.focus_entry()
            return
        self.set_entry(q)
        if self.settings["collapsed"]:
            self.expand()
        if not self.dict:
            self._show_message(q, "사전 데이터를 준비하는 중이에요. 잠시 후 다시 시도해 주세요.\n"
                                  "(처음 실행할 때 한 번 내려받아요. 아래 상태 표시줄을 확인해 주세요)")
            return
        try:
            res = self.dict.lookup(q)
        except Exception as e:
            self._show_message(q, f"검색 중 오류가 났어요: {e}")
            return
        self.result = res
        self._render_result(res)
        if res.found:
            self.history.add(res.headword)
            self._refresh_chips()
        self.entry.select_range(0, "end")

    def _render_result(self, res: Result):
        self.links.clear()
        if not res.found:
            self.lbl_word.config(text=res.query)
            self.lbl_ipa.config(text="")
            self._update_star()
            doc = Doc()
            doc.line((f"‘{res.query}’ 은(는) 오프라인 사전에 없어요.", "h1", None))
            doc.blank()
            if res.suggestions:
                segs = [("혹시 이 단어인가요?  ", "sec", None)]
                for i, w in enumerate(res.suggestions[:8]):
                    if i:
                        segs.append(("  ", None, None))
                    segs.append((w, "link", w))
                doc.line(*segs)
                doc.blank()
            doc.line(("→ 포털 사전에서 찾아보기", "link", "@web"))
            self._render(self.tabs["meaning"], doc)
            empty = Doc()
            empty.line(("검색 결과가 없어요.", "note", None))
            self._render(self.tabs["ety"], empty)
            self._render(self.tabs["ex"], empty)
            self.nb.select(0)
            return

        self.lbl_word.config(text=res.headword)
        self.lbl_ipa.config(text=res.ipa)
        self._update_star()
        self._render(self.tabs["meaning"], self._meaning_doc(res))
        self._render(self.tabs["ety"], res.etymology)
        self._render(self.tabs["ex"], res.examples)
        self.nb.select(0)

    def _meaning_doc(self, res: Result) -> Doc:
        doc = Doc()
        if res.redirected_from:
            doc.line((f"‘{res.redirected_from}’ → ‘{res.headword}’ 로 찾았어요", "note", None))
        doc.lines.extend(res.meaning.lines)
        if self.var_en.get() and res.lang == "en" and res.has_ko and not res.meaning_en.empty:
            doc.blank()
            doc.line(("영영 정의", "sec", None))
            doc.lines.extend(res.meaning_en.lines)
        return doc

    def _toggle_english(self):
        self.settings["show_english"] = bool(self.var_en.get())
        self.settings.save()
        if self.result and self.result.found:
            self._render(self.tabs["meaning"], self._meaning_doc(self.result))

    def _render(self, t: tk.Text, doc: Doc):
        t.config(state="normal")
        t.delete("1.0", "end")
        for line in doc.lines:
            start = t.index("end-1c")
            for text, style, link in line:
                tags = [style] if style else []
                if link:
                    tag = f"lnk{len(self.links)}"
                    self.links[tag] = link
                    tags = ["link", tag] + [s for s in tags if s != "link"]
                t.insert("end", text, tuple(tags))
            t.insert("end", "\n")
            t.tag_add("hang", start, "end-1c")
        t.config(state="disabled")
        t.yview_moveto(0)

    def _show_message(self, word: str, msg: str):
        self.lbl_word.config(text=word)
        self.lbl_ipa.config(text="")
        doc = Doc()
        for ln in msg.split("\n"):
            doc.line((ln, "note", None))
        self._render(self.tabs["meaning"], doc)
        self.nb.select(0)

    def _show_welcome(self):
        hk = self.settings["hotkey"]
        doc = Doc()
        doc.line(("QuickDic 사용법", "sec", None))
        doc.line(("1. ", "num", None), (f"다른 프로그램에서 단어를 드래그하고 {hk} 를 누르세요.", "ko", None))
        doc.line(("2. ", "num", None), ("또는 위 검색창에 직접 입력하거나 붙여넣고 Enter.", "ko", None))
        doc.line(("3. ", "num", None), ("결과 속 단어를 더블클릭하면 그 단어를 찾아요.", "ko", None))
        doc.line(("4. ", "num", None), ("‘웹사전’ 버튼은 네이버 사전 등 포털 검색 결과를 열어요.", "ko", None))
        doc.blank()
        doc.line(("단축키  ", "sec", None), ("Esc 접기 · Ctrl+L 검색창 · Ctrl+1/2/3 탭 이동", "dim", None))
        self._render(self.tabs["meaning"], doc)
        self.lbl_word.config(text="")
        self.lbl_ipa.config(text="")

    # 링크·더블클릭
    def _on_link(self, t: tk.Text):
        for tag in t.tag_names("current"):
            if tag in self.links:
                target = self.links[tag]
                if target == "@web":
                    self.open_web()
                else:
                    self.search(target)
                return "break"

    def _on_double_click(self, t: tk.Text, e):
        idx = t.index(f"@{e.x},{e.y}")
        word = t.get(f"{idx} wordstart", f"{idx} wordend").strip()
        word = clean_query(word)
        if word and len(word) > 1:
            self.root.after(10, lambda: self.search(word))
        return "break"

    def _copy_text(self, t: tk.Text):
        try:
            text = t.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        return "break"

    # 최근 검색
    def _refresh_chips(self):
        for w in self.chips.winfo_children():
            w.destroy()
        if not self.history.items:
            return
        tk.Label(self.chips, text="최근", bg=C["bg"], fg=C["dim"], font=self.f["small"]).pack(side="left", padx=(2, 4))
        for word in self.history.items[:8]:
            b = FlatButton(self.chips, word, lambda w=word: self.search(w), bg=C["chip"], fg=C["en"],
                           font=self.f["small"], padx=6, pady=1)
            b.pack(side="left", padx=2)

    # ------------------------------------------------------------------ 부가 기능
    def current_word(self) -> str:
        if self.result:
            return self.result.headword or self.result.query
        return clean_query(self.entry_text())

    def open_web(self):
        word = self.current_word() or clean_query(self.entry_text())
        name = self.settings["portal"]
        if word and is_korean(word):
            tpl = config.PORTALS_KO.get(name, config.PORTALS_KO["네이버 영어사전"])
        else:
            tpl = config.PORTALS.get(name, config.PORTALS["네이버 영어사전"])
        if not word:
            base = urllib.parse.urlsplit(tpl)
            winsys.open_url(f"{base.scheme}://{base.netloc}/")
            return
        winsys.open_url(tpl.format(q=urllib.parse.quote(word)))

    def pronounce(self):
        if not self.result or not self.result.found:
            return
        if not winsys.speak(self.result.headword, "ko" if self.result.lang == "ko" else "en"):
            self.status("발음 기능은 Windows 에서만 동작해요")

    def _summary(self) -> str:
        if not self.result:
            return ""
        for line in self.result.meaning.lines:
            parts = [t for t, s, _ in line if s in ("ko", "en")]
            if parts:
                return " ".join(parts)[:150]
        return ""

    def toggle_bookmark(self):
        if not self.result or not self.result.found:
            return
        on = self.bookmarks.toggle(self.result.headword, self._summary())
        self._update_star()
        self.status("단어장에 저장했어요" if on else "단어장에서 뺐어요")

    def _update_star(self):
        w = self.result.headword if self.result and self.result.found else ""
        on = bool(w) and self.bookmarks.has(w)
        self.btn_star.config(text="★" if on else "☆")

    # ------------------------------------------------------------------ 상태 표시
    def status(self, text: str, color: str | None = None):
        self.lbl_status.config(text=text, fg=color or C["dim"], cursor="arrow")

    def _idle_status(self):
        if self.dict:
            self.status(f"오프라인 사전 · {self.dict.version}")
        self.lbl_hint.config(text=f"{self.settings['hotkey']} 로 검색")

    # ------------------------------------------------------------------ 사전 파일
    def _open_db(self):
        if self.dict:
            self.dict.close()
            self.dict = None
        if os.path.exists(config.DB_PATH):
            try:
                self.dict = Dictionary(config.DB_PATH)
            except Exception as e:
                self.status(f"사전 파일을 열지 못했어요: {e}", C["tag"])
                return
            self._idle_status()
        else:
            self.status("사전 데이터를 처음 내려받을 준비 중…")
            self.lbl_hint.config(text=f"{self.settings['hotkey']} 로 검색")

    def _maybe_update(self):
        if self.updater.is_due():
            self.updater.check_async()

    def _hourly(self):
        self._maybe_update()
        self.root.after(3600 * 1000, self._hourly)

    def _check_app_update(self):
        if config.APP_VERSION == "dev":
            return

        def work():
            tag, url = updater.fetch_latest_app_version()
            if tag and tag.lstrip("v") != config.APP_VERSION.lstrip("v"):
                self.q.put(("app_update", (tag, url)))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ 단축키
    def _start_hotkey(self):
        if self.hotkey:
            self.hotkey.stop()
            self.hotkey.join(1.5)  # 이전 단축키 해제를 기다린 뒤 새로 등록
        hk = self.settings["hotkey"]
        self.hotkey = winsys.HotkeyListener(hk, self._on_hotkey)
        self.hotkey.start()
        self.hotkey.ready.wait(2)
        if winsys.IS_WIN and not self.hotkey.ok:
            self.status(f"{hk} 단축키를 쓸 수 없어요(다른 프로그램이 사용 중). 설정에서 바꿔 주세요.", C["tag"])

    def _on_hotkey(self):
        """단축키 스레드에서 호출됨 → 선택 글자 복사는 또 다른 스레드에서"""
        def grab():
            text = winsys.copy_selection(self.settings["hotkey"], bool(self.settings["restore_clipboard"]))
            self.q.put(("hotkey", text))
        threading.Thread(target=grab, daemon=True).start()

    # ------------------------------------------------------------------ 메시지 처리
    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "hotkey":
                    self.bring_to_front()
                    if val and clean_query(val):
                        self.search(val, from_hotkey=True)
                    else:
                        self.focus_entry()
                elif kind == "status":
                    self.status(val)
                elif kind == "progress":
                    pass
                elif kind == "error":
                    self.status(val, C["tag"])
                    if self.dict:
                        self.root.after(15000, self._idle_status)
                elif kind == "db_ready":
                    self._install_db(val)
                elif kind == "app_update":
                    tag, url = val
                    self.app_update_url = url
                    self.lbl_status.config(text=f"새 버전 {tag} 이 나왔어요 — 여기를 눌러 받기",
                                           fg=C["accent"], cursor="hand2")
        except queue.Empty:
            pass
        self.root.after(60, self._poll)

    def _install_db(self, new_path: str):
        first = self.dict is None
        if self.dict:
            self.dict.close()
            self.dict = None
        try:
            updater.install_new_db(new_path)
        except OSError as e:
            self.status(f"사전 교체 실패: {e}", C["tag"])
        self._open_db()
        if self.dict:
            self.status(("사전 준비 완료! " if first else "사전을 최신으로 바꿨어요 · ") + self.dict.version, C["accent"])
            self.root.after(10000, self._idle_status)
            q = clean_query(self.entry_text())
            if first and q:
                self.search(q)

    # ------------------------------------------------------------------ 단어장 창
    def open_wordbook(self):
        win = tk.Toplevel(self.root)
        win.title("단어장")
        win.configure(bg=C["bg"])
        win.attributes("-topmost", True)
        win.geometry(f"520x420+{self.root.winfo_x() - 60}+{self.root.winfo_y() + 40}")
        cols = ("word", "meaning", "added")
        tv = ttk.Treeview(win, columns=cols, show="headings")
        for c, label, w in (("word", "단어", 120), ("meaning", "뜻", 280), ("added", "저장일", 110)):
            tv.heading(c, text=label)
            tv.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(win, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)

        def reload():
            tv.delete(*tv.get_children())
            for b in self.bookmarks.items:
                tv.insert("", "end", values=(b["word"], b.get("meaning", ""), b.get("added", "")))
            info.config(text=f"모두 {len(self.bookmarks.items)}개")

        def open_sel(_=None):
            sel = tv.selection()
            if sel:
                self.search(tv.item(sel[0])["values"][0])
                self.bring_to_front()

        def delete_sel():
            for s in tv.selection():
                self.bookmarks.remove(str(tv.item(s)["values"][0]))
            reload()
            self._update_star()

        def export():
            path = filedialog.asksaveasfilename(parent=win, defaultextension=".csv",
                                                filetypes=[("CSV (엑셀)", "*.csv")], initialfile="QuickDic_단어장.csv")
            if path:
                self.bookmarks.export_csv(path)
                messagebox.showinfo("단어장", "저장했어요.\n" + path, parent=win)

        btns = tk.Frame(win, bg=C["bg"])
        btns.pack(side="bottom", fill="x", padx=8, pady=6)
        info = tk.Label(btns, text="", bg=C["bg"], fg=C["dim"], font=self.f["small"])
        info.pack(side="left")
        ttk.Button(btns, text="CSV로 내보내기", command=export).pack(side="right")
        ttk.Button(btns, text="선택 삭제", command=delete_sel).pack(side="right", padx=6)
        sb.pack(side="right", fill="y", pady=(8, 0))
        tv.pack(fill="both", expand=True, padx=(8, 0), pady=(8, 0))
        tv.bind("<Double-1>", open_sel)
        reload()

    # ------------------------------------------------------------------ 설정 창
    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("QuickDic 설정")
        win.configure(bg=C["bg"])
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.geometry(f"+{max(0, self.root.winfo_x() - 80)}+{self.root.winfo_y() + 30}")
        pad = dict(padx=12, pady=5, sticky="w")
        row = 0

        def label(text):
            tk.Label(win, text=text, bg=C["bg"], font=self.f["ui"]).grid(row=row, column=0, **pad)

        # 웹사전
        label("웹사전 버튼으로 열 사전")
        v_portal = tk.StringVar(value=self.settings["portal"])
        cb = ttk.Combobox(win, textvariable=v_portal, values=list(config.PORTALS), state="readonly", width=22)
        cb.grid(row=row, column=1, **pad)
        row += 1

        # 단축키
        label("검색 단축키")
        v_hk = tk.StringVar(value=self.settings["hotkey"])
        ttk.Combobox(win, textvariable=v_hk, values=winsys.HOTKEY_CHOICES, state="readonly", width=22).grid(
            row=row, column=1, **pad)
        row += 1

        # 투명도
        label("창 불투명도")
        v_op = tk.IntVar(value=int(self.settings["opacity"]))
        op_lbl = tk.Label(win, text=f"{v_op.get()}%", bg=C["bg"], font=self.f["small"], width=5)
        sc = ttk.Scale(win, from_=50, to=100, orient="horizontal", length=150,
                       command=lambda v: (self.set_opacity(float(v)), op_lbl.config(text=f"{int(float(v))}%")))
        sc.set(v_op.get())
        sc.grid(row=row, column=1, padx=12, pady=5, sticky="w")
        op_lbl.grid(row=row, column=1, padx=12, sticky="e")
        row += 1

        # 글자 크기
        label("글자 크기 (다시 시작 후 적용)")
        v_fs = tk.IntVar(value=int(self.settings["font_size"]))
        ttk.Spinbox(win, from_=9, to=16, textvariable=v_fs, width=5).grid(row=row, column=1, **pad)
        row += 1

        checks = [
            ("항상 다른 창 위에 표시", "topmost"),
            ("다른 창을 누르면 자동으로 접기", "auto_collapse"),
            ("단축키 검색 후 클립보드 원래대로 되돌리기", "restore_clipboard"),
            ("사전 자동 업데이트 (주 1회)", "auto_update"),
        ]
        vars_ = {}
        for text, key in checks:
            vars_[key] = tk.BooleanVar(value=bool(self.settings[key]))
            ttk.Checkbutton(win, text=text, variable=vars_[key]).grid(row=row, column=0, columnspan=2, **pad)
            row += 1
        v_auto = tk.BooleanVar(value=winsys.get_autostart())
        cbx = ttk.Checkbutton(win, text="Windows 시작할 때 자동 실행", variable=v_auto)
        cbx.grid(row=row, column=0, columnspan=2, **pad)
        if not winsys.IS_WIN:
            cbx.state(["disabled"])
        row += 1

        ttk.Separator(win).grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=6)
        row += 1

        # 사전 정보
        ver = self.dict.version if self.dict else "없음"
        last = (self.settings["last_update_check"] or "-").replace("T", " ")[:16]
        tk.Label(win, text=f"사전 버전: {ver}    마지막 확인: {last}", bg=C["bg"], fg=C["dim"],
                 font=self.f["small"]).grid(row=row, column=0, columnspan=2, **pad)
        row += 1
        bf = tk.Frame(win, bg=C["bg"])
        bf.grid(row=row, column=0, columnspan=2, sticky="w", padx=8)
        ttk.Button(bf, text="지금 업데이트 확인",
                   command=lambda: (self.updater.check_async(force=True), self.status("사전 업데이트 확인 중…"))
                   ).pack(side="left", padx=4)
        ttk.Button(bf, text="사전 파일 직접 열기…", command=lambda: self._import_db(win)).pack(side="left", padx=4)
        ttk.Button(bf, text="최근 기록 지우기",
                   command=lambda: (self.history.clear(), self._refresh_chips())).pack(side="left", padx=4)
        row += 1

        about = tk.Label(win, text=f"QuickDic {config.APP_VERSION}  ·  사전 데이터: Wiktionary (CC BY-SA 4.0), "
                                   "kaikki.org", bg=C["bg"], fg=C["accent"], font=self.f["small"], cursor="hand2")
        about.grid(row=row, column=0, columnspan=2, padx=12, pady=(8, 2), sticky="w")
        about.bind("<Button-1>", lambda e: winsys.open_url("https://kaikki.org/"))
        row += 1

        def save_close():
            s = self.settings
            s["portal"] = v_portal.get()
            s["font_size"] = int(v_fs.get())
            for _, key in checks:
                s[key] = bool(vars_[key].get())
            self.set_topmost(bool(vars_["topmost"].get()))
            if winsys.IS_WIN and v_auto.get() != winsys.get_autostart():
                winsys.set_autostart(bool(v_auto.get()))
            if v_hk.get() != s["hotkey"]:
                s["hotkey"] = v_hk.get()
                self._start_hotkey()
                if not self.entry_text():
                    self.entry.delete(0, "end")
                    self._placeholder_on = False
                    self._set_placeholder()
            s.save()
            self._idle_status() if self.dict else None
            win.destroy()

        ttk.Button(win, text="저장", command=save_close).grid(row=row, column=1, padx=12, pady=10, sticky="e")
        win.protocol("WM_DELETE_WINDOW", save_close)

    def _import_db(self, parent):
        path = filedialog.askopenfilename(parent=parent, filetypes=[("QuickDic 사전", "*.db *.db.gz")])
        if not path:
            return
        import gzip
        import shutil
        dst = config.DB_PATH + ".new"
        try:
            if path.endswith(".gz"):
                with gzip.open(path, "rb") as s, open(dst, "wb") as d:
                    shutil.copyfileobj(s, d)
            else:
                shutil.copyfile(path, dst)
            if not updater.local_db_version(dst):
                raise ValueError("QuickDic 사전 파일이 아니에요")
        except Exception as e:
            messagebox.showerror("사전 파일", f"불러오지 못했어요: {e}", parent=parent)
            return
        self._install_db(dst)

    # ------------------------------------------------------------------ 종료
    def quit(self):
        self._save_geometry()
        self.settings.save()
        if self.hotkey:
            self.hotkey.stop()
        if self.dict:
            self.dict.close()
        self.root.destroy()


def main():
    if not winsys.acquire_single_instance(TITLE):
        return
    winsys.enable_dpi_awareness()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
