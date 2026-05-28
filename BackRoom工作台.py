
"""
依赖：requests, tkinter（标准库）
"""
from __future__ import annotations
import threading
import time
import json
import os
import sys
import requests
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Any, Dict, List, Tuple

# === 配置 ===
API_URL = (
   这里填你的小站入站申请帖的API
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.bilibili.com/",
}


def fetch_api(url: str = API_URL, timeout: int = 15) -> Tuple[Dict[str, Any] | None, str | None]:
    """请求 API 并返回 JSON（dict）或错误信息。"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        # 尝试返回片段用于诊断
        try:
            snippet = r.text[:800] if 'r' in locals() and hasattr(r, 'text') else ''
        except Exception:
            snippet = ''
        return None, f"{e} | snippet={snippet}"


def extract_value(item: Dict[str, Any], candidates: List[List[str]]) -> Any:
    """按候选路径尝试提取值，返回第一个找到的非空值。"""
    for path in candidates:
        cur = item
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok and cur not in (None, '', []):
            return cur
    return ''


def parse_api_data(data: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """解析 API JSON，返回剩余帖子数和 dyn_list 列表（每项为解析后字典）。"""
    if not isinstance(data, dict):
        return 0, []
    content = data.get('data', {}).get('content', {})
    remaining = content.get('count', 0)
    dyn_list = content.get('dyn_list') or []

    parsed = []
    for idx, item in enumerate(dyn_list):
        if not isinstance(item, dict):
            parsed.append({'index': idx, 'raw': item})
            continue

        title = extract_value(item, [['title'], ['card', 'title'], ['desc'], ['title_text']])
        author = extract_value(item, [['meta', 'author'], ['author', 'uname'], ['author', 'name'], ['author'], ['user_name']])
        time_text = extract_value(item, [['meta', 'time_text'], ['time_text'], ['publish_time'], ['ctime'], ['timestamp']])
        # 数字时间戳转换
        if isinstance(time_text, (int, float)) and time_text > 0:
            try:
                if time_text > 1e12:
                    # 毫秒 -> 秒
                    time_text = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time_text / 1000))
                elif time_text > 1e9:
                    time_text = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time_text))
            except Exception:
                time_text = str(time_text)

        replies = extract_value(item, [['meta', 'reply_count'], ['meta', 'text'], ['reply_count'], ['reply', 'count'], ['comment_count'], ['stats', 'reply']])
        try:
            replies = int(replies) if replies != '' else 0
        except Exception:
            try:
                replies = int(str(replies))
            except Exception:
                replies = 0

        jump_uri = extract_value(item, [['jump_uri'], ['uri'], ['link'], ['card', 'jump_uri']])

        parsed.append(
            {
                'index': idx,
                'title': str(title) if title is not None else '',
                'author': str(author) if author is not None else '',
                'time_text': str(time_text) if time_text is not None else '',
                'replies': replies,
                'jump_uri': str(jump_uri) if jump_uri is not None else '',
                'raw': item,
            }
        )

    return int(remaining or 0), parsed


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        # 程序根目录：打包后取可执行文件目录，脚本运行则取脚本所在目录
        try:
            if getattr(sys, 'frozen', False):
                self.program_root = os.path.dirname(sys.executable)
            else:
                self.program_root = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            self.program_root = os.getcwd()
        root.title('BackRoom小站工作台')
        root.geometry('2500x64')
        style = ttk.Style(root)
        try:
            style.configure('TButton', padding=(6, 4))
        except Exception:
            pass

        frm = ttk.Frame(root)
        frm.pack(fill='x', padx=8, pady=6)

        ttk.Label(frm, text='刷新间隔(分钟-修改后需重新停止再开启):').pack(side='left')
        self.interval_var = tk.StringVar(value='1')
        ttk.Entry(frm, width=6, textvariable=self.interval_var).pack(side='left', padx=6)

        self.start_btn = ttk.Button(frm, text='开始定时刷新', command=self.start_timer)
        self.start_btn.pack(side='left', padx=4)
        self.stop_btn = ttk.Button(frm, text='停止', command=self.stop_timer, state='disabled')
        self.stop_btn.pack(side='left', padx=4)

        ttk.Button(frm, text='立即刷新', command=self.start_fetch_thread).pack(side='left', padx=8)

        # 页码范围设置：开始页 - 结束页
        ttk.Label(frm, text='多页搜索：开始页:').pack(side='left', padx=(8, 0))
        self.start_page_var = tk.StringVar(value='1')
        ttk.Entry(frm, width=4, textvariable=self.start_page_var).pack(side='left', padx=(2, 6))
        ttk.Label(frm, text='结束页:').pack(side='left')
        self.end_page_var = tk.StringVar(value='5')
        ttk.Entry(frm, width=4, textvariable=self.end_page_var).pack(side='left', padx=(2, 6))

        ttk.Button(frm, text='↻', width=2, command=self.start_fetch_thread).pack(side='left', padx=(0, 8))

        self.remain_label = ttk.Label(frm, text='剩余帖子数: -')
        self.remain_label.pack(side='right')

        # Treeview
        cols = ('index', 'title', 'author', 'time', 'replies', 'jump')
        # 中心内容区：用于放置主列表(Treeview)与右侧自定义文本区
        content = ttk.Frame(root)
        content.pack(fill='both', expand=True, padx=8, pady=8)

        self.tree = ttk.Treeview(content, columns=cols, show='headings')
        self.tree.heading('index', text='序号')
        self.tree.heading('title', text='标题')
        self.tree.heading('author', text='作者')
        self.tree.heading('time', text='发布时间')
        self.tree.heading('replies', text='回复')
        self.tree.heading('jump', text='跳转链接')
        self.tree.column('index', width=30, anchor='center')
        self.tree.column('title', width=200)
        self.tree.column('author', width=100)
        self.tree.column('time', width=50)
        self.tree.column('replies', width=30, anchor='center')
        self.tree.column('jump', width=300)

        vsb = ttk.Scrollbar(content, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(fill='both', expand=True, side='left')
        vsb.pack(fill='y', side='right')

        # 右侧可编辑持久化文本区（最小化改动，保持原有布局）
        try:
            right_frame = ttk.Frame(content, width=360)
            right_frame.pack(fill='y', side='right', padx=(8, 0), pady=0)
            ttk.Label(right_frame, text='自定义文本:').pack(anchor='nw')
            self.custom_text = scrolledtext.ScrolledText(right_frame, width=40, height=16)
            self.custom_text.pack(fill='both', expand=True, pady=6)
            btns = ttk.Frame(right_frame)
            btns.pack(fill='x')
            ttk.Button(btns, text='保存', command=lambda: self.save_custom_text(True)).pack(side='left', padx=(0, 6))
            ttk.Button(btns, text='一键复制', command=lambda: self.copy_custom_text()).pack(side='left')

            # 持久化文件路径（程序所在目录下 custom_text.txt）
            self.custom_text_path = os.path.join(self.program_root, 'custom_text.txt')
            try:
                if os.path.exists(self.custom_text_path):
                    with open(self.custom_text_path, 'r', encoding='utf-8') as f:
                        txt = f.read()
                    self.custom_text.insert('1.0', txt)
            except Exception:
                pass

            # 绑定修改事件：按键防抖保存 & 失去焦点立即保存
            try:
                self.custom_text.bind('<KeyRelease>', lambda e: self.schedule_save_custom_text())
                self.custom_text.bind('<FocusOut>', lambda e: self.save_custom_text(False))
            except Exception:
                pass
        except Exception:
            # 若右侧面板创建失败，不影响主功能
            # 始终将持久化文件保存在程序所在目录
            self.custom_text = None
            self.custom_text_path = os.path.join(self.program_root, 'custom_text.txt')

        # 行和高亮样式
        try:
            self.tree.tag_configure('zero', foreground='red')
            self.tree.tag_configure('even', background='#fbfbfb')
            self.tree.tag_configure('odd', background='#ffffff')
        except Exception:
            pass

        # 下方日志/详情框
        bottom = ttk.Frame(root)
        bottom.pack(fill='x', padx=8, pady=(0, 8))
        self.detail_btn = ttk.Button(bottom, text='查看详情', command=self.show_selected_detail)
        self.detail_btn.pack(side='left')
        self.open_btn = ttk.Button(bottom, text='打开跳转链接', command=self.open_selected_link)
        self.open_btn.pack(side='left', padx=8)
        self.open_btn = ttk.Button(bottom, text='关于工具', command=self.open_github)
        self.open_btn.pack(side='left', padx=8)

        self.logbox = scrolledtext.ScrolledText(root, height=8, state='disabled')
        self.logbox.pack(fill='x', padx=8, pady=(0, 8))

        self.after_id = None
        # 自定义文本保存防抖定时器 id
        self._save_after_id = None
        self.running = False
        self.current_items: List[Dict[str, Any]] = []
        # 自动调整窗口尺寸的状态：首次允许自动收缩/扩展，之后只允许放大
        self._auto_sized_done = False
        self._min_w = None
        self._min_h = None
        # 记录是否已在首次更新时执行过自动调整（防止后续刷新调整窗口）
        self._initial_adjust_done = False

        # 启动时静默获取一次
        self.start_fetch_thread()
        # 启动自动定时刷新（延迟调用，确保界面初始化完成）
        self.root.after(800, self.start_timer)

        # 关闭时保存自定义文本
        try:
            self.root.protocol('WM_DELETE_WINDOW', self.on_closing)
        except Exception:
            pass

        # 双击改为直接打开跳转链接
        self.tree.bind('<Double-1>', self.on_double_click)

    def log(self, msg: str):
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        self.logbox.configure(state='normal')
        self.logbox.insert('end', f'[{ts}] {msg}\n')
        self.logbox.see('end')
        self.logbox.configure(state='disabled')

    def start_fetch_thread(self, start_page: int | None = None, end_page: int | None = None):
        # 读取页码（在主线程读取 Tk 变量），并启动后台线程执行请求
        try:
            sp = int(start_page) if start_page is not None else int(self.start_page_var.get())
        except Exception:
            sp = 1
        try:
            ep = int(end_page) if end_page is not None else int(self.end_page_var.get())
        except Exception:
            ep = sp
        if sp <= 0:
            sp = 1
        if ep < sp:
            ep = sp
        t = threading.Thread(target=self._fetch_job, args=(sp, ep), daemon=True)
        t.start()

    def _fetch_job(self, start_page: int = 1, end_page: int = 1):
        self.root.after(0, lambda: self.log(f'开始请求 API，页码 {start_page} - {end_page} ...'))

        all_items: List[Dict[str, Any]] = []
        seen_ids: set = set()
        remaining_first = None

        for page in range(start_page, end_page + 1):
            try:
                # 将 API_URL 中的 page_num= 替换为当前页
                page_url = API_URL.replace('page_num=1', f'page_num={page}')
                data, err = fetch_api(page_url)
                if err:
                    self.root.after(0, lambda p=page, e=err: self.log(f'第 {p} 页请求失败: {e}'))
                    continue
                remaining, items = parse_api_data(data)
                if remaining_first is None:
                    remaining_first = remaining

                for it in items:
                    raw = it.get('raw', {}) or {}
                    # 尝试用 dyn_id 或 jump_uri 做去重键
                    idkey = raw.get('dyn_id') or it.get('jump_uri') or raw.get('id') or str(raw)
                    if idkey in seen_ids:
                        continue
                    seen_ids.add(idkey)
                    it['page'] = page
                    all_items.append(it)
            except Exception as e:
                self.root.after(0, lambda p=page, e=e: self.log(f'第 {p} 页处理失败: {e}'))

        # 重新分配索引
        for i, it in enumerate(all_items):
            it['index'] = i

        self.current_items = all_items
        rem_display = int(remaining_first or 0)
        self.root.after(0, lambda: self.update_ui(rem_display, all_items))
        self.root.after(0, lambda: self.log(f'更新完成，合并后共 {len(all_items)} 条（去重后），来源页 {start_page}-{end_page}，剩余帖子数(首页): {rem_display}'))

    def update_ui(self, remaining: int, items: List[Dict[str, Any]]):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for it in items:
            title = it.get('title') or ''
            if len(title) > 160:
                title_display = title[:156] + '...'
            else:
                title_display = title
            tags = []
            try:
                if int(it.get('index', 0)) % 2 == 0:
                    tags.append('even')
                else:
                    tags.append('odd')
            except Exception:
                tags.append('odd')
            try:
                if int(it.get('replies', 0)) == 0:
                    tags.append('zero')
            except Exception:
                pass
            self.tree.insert('', 'end', values=(it.get('index'), title_display, it.get('author'), it.get('time_text'), it.get('replies'), it.get('jump_uri')), tags=tuple(tags))
        self.remain_label.config(text=f'剩余帖子数: {remaining}')
        # 只在首次更新时尝试自动调整窗口尺寸，之后刷新不改变窗口大小
        if not getattr(self, '_initial_adjust_done', False):
            self.adjust_window_size_to_content(items)
            self._initial_adjust_done = True

    def get_selected_item(self) -> Dict[str, Any] | None:
        sel = self.tree.selection()
        if not sel:
            return None
        vals = self.tree.item(sel[0], 'values')
        if not vals:
            return None
        idx = int(vals[0])
        for it in self.current_items:
            if it.get('index') == idx:
                return it
        return None

    def show_selected_detail(self):
        it = self.get_selected_item()
        if not it:
            messagebox.showinfo('提示', '请先选择一条记录')
            return
        win = tk.Toplevel(self.root)
        win.title('条目详情')
        win.geometry('800x520')
        # 详情文本区
        try:
            frame = ttk.Frame(win)
            frame.pack(fill='both', expand=True, padx=8, pady=8)

            detail_txt = scrolledtext.ScrolledText(frame, wrap='none')
            detail_txt.pack(fill='both', expand=True)

            try:
                raw = it.get('raw', {}) or it
                pretty = json.dumps(raw, ensure_ascii=False, indent=2)
            except Exception:
                pretty = str(it)

            detail_txt.insert('1.0', pretty)
            # 禁止编辑但允许选择复制
            detail_txt.configure(state='disabled')

            # 按钮区：复制 JSON / 打开链接 / 关闭
            btns = ttk.Frame(win)
            btns.pack(fill='x', padx=8, pady=(0, 8))

            def _copy_json():
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(pretty)
                    self.log('条目 JSON 已复制到剪贴板')
                    try:
                        messagebox.showinfo('已复制', '已将 JSON 复制到剪贴板')
                    except Exception:
                        pass
                except Exception as e:
                    try:
                        messagebox.showerror('复制失败', str(e))
                    except Exception:
                        pass

            def _open_link():
                url = it.get('jump_uri') or it.get('raw', {}).get('jump_uri') or it.get('raw', {}).get('uri')
                if not url:
                    try:
                        messagebox.showinfo('提示', '未找到跳转链接')
                    except Exception:
                        pass
                    return
                try:
                    webbrowser.open(url)
                except Exception as e:
                    try:
                        messagebox.showerror('错误', f'打开失败: {e}')
                    except Exception:
                        pass

            ttk.Button(btns, text='复制 JSON', command=_copy_json).pack(side='left')
            ttk.Button(btns, text='打开跳转链接', command=_open_link).pack(side='left', padx=8)
            ttk.Button(btns, text='关闭', command=win.destroy).pack(side='right')
        except Exception:
            # 若显示失败，弹出原始 JSON 作为兜底
            try:
                messagebox.showinfo('条目原始数据', str(it.get('raw', {}) or it))
            except Exception:
                pass

    def open_github(self):
        try:
            webbrowser.open("https://github.com/MLFK-MLFK/Bilibili-BackgroundDevTool")
        except Exception as e:
            messagebox.showerror('错误', f'打开失败: {e}') 

    def open_selected_link(self):
        it = self.get_selected_item()
        if not it:
            messagebox.showinfo('提示', '请先选择一条记录')
            return
        url = it.get('jump_uri') or it.get('raw', {}).get('jump_uri') or it.get('raw', {}).get('uri')
        if not url:
            messagebox.showinfo('提示', '未找到跳转链接')
            return
        try:
            webbrowser.open(url)
        except Exception as e:
            messagebox.showerror('错误', f'打开失败: {e}')

    def on_double_click(self, event):
        # 直接打开被双击行的跳转链接
        rowid = self.tree.identify_row(event.y)
        if not rowid:
            return
        vals = self.tree.item(rowid, 'values')
        if not vals:
            return
        try:
            idx = int(vals[0])
        except Exception:
            return
        for it in self.current_items:
            if it.get('index') == idx:
                url = it.get('jump_uri') or it.get('raw', {}).get('jump_uri') or it.get('raw', {}).get('uri')
                if not url:
                    messagebox.showinfo('提示', '未找到跳转链接')
                    return
                try:
                    webbrowser.open(url)
                except Exception as e:
                    messagebox.showerror('错误', f'打开失败: {e}')
                return

    def adjust_window_size_to_content(self, items: List[Dict[str, Any]]):
        # 尝试根据内容行数和列宽调整窗口大小，以尽量展示全部内容
        try:
            self.root.update_idletasks()
            cols = ('index', 'title', 'author', 'time', 'replies', 'jump')
            total_col_width = 0
            for c in cols:
                info = self.tree.column(c)
                w = info.get('width') if isinstance(info, dict) else info
                total_col_width += int(w or 120)

            width = total_col_width + 80

            rows = max(1, len(items))
            row_height = 22
            children = self.tree.get_children()
            if children:
                bbox = self.tree.bbox(children[0])
                if bbox and len(bbox) >= 4 and bbox[3] > 0:
                    row_height = bbox[3]

            header_height = 30
            tree_height = header_height + rows * row_height
            controls_height = 100
            logbox_height = 160
            total_height = controls_height + tree_height + logbox_height + 40

            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            width = min(width, screen_w - 80)
            total_height = min(total_height, screen_h - 80)

            # 首次自动调整：允许收缩或放大以完全显示内容；之后只允许放大，避免刷新时窗口缩小
            if not getattr(self, '_auto_sized_done', False):
                # 记录最小尺寸为首次计算值
                self._min_w = int(width)
                self._min_h = int(total_height)
                try:
                    self.root.geometry(f"{self._min_w}x{self._min_h}")
                except Exception:
                    pass
                self._auto_sized_done = True
            else:
                try:
                    cur_w = int(self.root.winfo_width() or 0)
                    cur_h = int(self.root.winfo_height() or 0)
                except Exception:
                    cur_w, cur_h = 0, 0
                target_w = max(self._min_w or 0, int(width), cur_w)
                target_h = max(self._min_h or 0, int(total_height), cur_h)
                # 若需要放大则调整
                if target_w > cur_w or target_h > cur_h:
                    try:
                        self.root.geometry(f"{int(target_w)}x{int(target_h)}")
                        # 更新记录的最小尺寸为新的较大值，避免后续缩小
                        self._min_w = max(self._min_w or 0, target_w)
                        self._min_h = max(self._min_h or 0, target_h)
                    except Exception:
                        pass
        except Exception:
            pass

    def start_timer(self):
        try:
            m = float(self.interval_var.get())
            if m <= 0:
                raise ValueError()
        except Exception:
            messagebox.showerror('错误', '请输入正数分钟数')
            return
        if self.running:
            self.log('定时器已在运行')
            return
        self.running = True
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.interval_ms = int(m * 60 * 1000)
        self.log(f'开始定时，每 {m} 分钟刷新一次')
        self._schedule_next()

    def _schedule_next(self):
        if not self.running:
            return
        self.after_id = self.root.after(self.interval_ms, self._timer_job)

    def _timer_job(self):
        self.start_fetch_thread()
        self._schedule_next()

    def stop_timer(self):
        if not self.running:
            return
        self.running = False
        if self.after_id:
            try:
                self.root.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.log('已停止定时')

    # -------- 自定义文本持久化与复制功能 --------
    def schedule_save_custom_text(self):
        try:
            if getattr(self, '_save_after_id', None):
                try:
                    self.root.after_cancel(self._save_after_id)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            # 自动保存不弹窗，手动保存会弹窗
            self._save_after_id = self.root.after(1000, lambda: self.save_custom_text(False))
        except Exception:
            self._save_after_id = None

    def save_custom_text(self, user_triggered: bool = False):
        if getattr(self, 'custom_text', None) is None:
            return
        try:
            txt = self.custom_text.get('1.0', 'end-1c')
            # 确保目录存在（通常为脚本目录）
            try:
                os.makedirs(os.path.dirname(self.custom_text_path), exist_ok=True)
            except Exception:
                pass
            with open(self.custom_text_path, 'w', encoding='utf-8') as f:
                f.write(txt)
            self.log(f'自定义文本已保存: {self.custom_text_path}')
            if user_triggered:
                try:
                    messagebox.showinfo('已保存', f'已保存到: {self.custom_text_path}')
                except Exception:
                    pass
        except Exception as e:
            self.log(f'保存自定义文本失败: {e}')
            if user_triggered:
                try:
                    messagebox.showerror('保存失败', str(e))
                except Exception:
                    pass

    def copy_custom_text(self):
        if getattr(self, 'custom_text', None) is None:
            messagebox.showinfo('提示', '自定义文本不可用')
            return
        try:
            txt = self.custom_text.get('1.0', 'end-1c')
            if not txt:
                messagebox.showinfo('提示', '自定义文本为空')
                return
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(txt)
            except Exception:
                pass
            # 同步保存
            self.save_custom_text()
            self.log('自定义文本已复制到剪贴板')
        except Exception as e:
            self.log(f'复制自定义文本失败: {e}')

    def on_closing(self):
        try:
            self.save_custom_text()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            try:
                self.root.quit()
            except Exception:
                pass


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
