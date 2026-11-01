"""One device card, independent of device protocols and service scheduling."""

import time
import tkinter as tk
from tkinter import ttk


class BatteryCard:
    def __init__(self, parent, name, index):
        frame = tk.Frame(parent, bg='#0b1220')
        frame.pack(fill='x', pady=(0, 10))
        self.title = tk.Label(frame, text=name, bg='#0b1220', fg='#e2e8f0', font=('Sans', 19, 'bold'))
        self.title.pack(anchor='w', pady=(4, 8))
        self.number = tk.Label(frame, text='?', bg='#0b1220', fg='#94a3b8', font=('Sans', 58, 'bold'))
        self.number.pack(anchor='w')
        self.style = ttk.Style(frame)
        self.style_name = f'Battery{index}.Horizontal.TProgressbar'
        self.style.configure(self.style_name, troughcolor='#1e293b', background='#94a3b8', borderwidth=0)
        self.progress = ttk.Progressbar(frame, style=self.style_name, maximum=100)
        self.progress.pack(fill='x', pady=(0, 12))
        self.status = tk.Label(frame, text='正在读取…', bg='#0b1220', fg='#94a3b8',
                               font=('Sans', 11), anchor='w', justify='left', wraplength=360)
        self.status.pack(fill='x')
        self.source = tk.Label(frame, text='来源：等待数据', bg='#0b1220', fg='#64748b',
                               font=('Sans', 9), anchor='w', justify='left', wraplength=360)
        self.source.pack(fill='x', pady=(8, 0))

    def render(self, result):
        value = result.get('percent')
        valid = result['status'] == 'ok'
        color = '#94a3b8' if not valid else '#42d785' if value >= 60 else '#ffca3a' if value >= 30 else '#ff6170'
        self.title.config(text=result.get('device') or '无线设备')
        self.number.config(text='?' if value is None else f'{value:g}%', fg=color)
        self.progress['value'] = value or 0
        self.style.configure(self.style_name, background=color)
        stamp = result.get('updated_at')
        when = time.strftime('%H:%M:%S', time.localtime(stamp)) if stamp else '采样时间未知'
        state = f'最近成功更新 {when}' if valid else ('上次电量已过期 · ' if value is not None else '') + result['reason']
        self.status.config(text=state)
        self.source.config(text='来源：' + (result.get('source') or '尚无有效数据'))
