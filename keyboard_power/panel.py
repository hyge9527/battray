"""Tk main thread + pipe notifications; no periodic worker-queue polling."""

import json
import os
import queue
import signal
import tkinter as tk
from tkinter import messagebox, ttk

from .application.service import ApplicationService
from .application.targets import selectors, targets_for_args
from .presentation.card import BatteryCard
from .runtime import Instance, command
from .settings import autostart_status, load_settings, save_interval, set_autostart
from .tray import Tray


class Panel:
    def __init__(self, args, instance):
        self.args, self.instance = args, instance
        self.events = queue.Queue()
        self.pipe_r, self.pipe_w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.closing, self.tray_available, self.bus_name = False, False, None
        self.service = ApplicationService()
        self.targets = targets_for_args(args)
        self.primary = self.targets[0].binding_id
        self.clients = {}
        self.debug_window = None
        self.interval = args.interval or load_settings()['interval']
        self.devices_data = {t.binding_id: {'device': t.name, 'percent': None, 'status': 'unknown', 'reason': '正在读取…'} for t in self.targets}
        self.data = self.devices_data[self.primary]
        self.root = tk.Tk(className='KeyboardPower')
        self.root.title('键盘电量 · ' + self.targets[0].name)
        self.root.geometry('440x460')
        self.root.minsize(400, 430)
        self.root.configure(bg='#0b1220')
        self.root.protocol('WM_DELETE_WINDOW', self.hide)
        self._widgets()
        self.root.createfilehandler(self.pipe_r, tk.READABLE, self._pump)
        self.root.createfilehandler(instance.socket, tk.READABLE, self._accept)
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: self.notify('quit', None))
        self.tray = Tray(self.notify, args.debug)
        self.tray.start()
        trace = (lambda name, data: print(name, data.hex(' '), flush=True)) if args.debug else None
        for target in self.targets:
            self.service.watch(target, lambda key, result: self.notify('result', (key, result)), self.interval, trace)
        if args.debug_panel:
            self.open_debug()

    def _widgets(self):
        font = ('Sans', 11)
        outer = tk.Frame(self.root, bg='#0b1220')
        outer.pack(fill='both', expand=True, padx=24, pady=22)
        tk.Label(outer, text='无线键盘电量', bg='#0b1220', fg='#94a3b8', font=font).pack(anchor='w')
        ttk.Style(self.root).theme_use('clam')
        viewport = tk.Frame(outer, bg='#0b1220')
        viewport.pack(fill='both', expand=True, pady=(0, 10))
        canvas = tk.Canvas(viewport, bg='#0b1220', highlightthickness=0, height=260)
        scrollbar = ttk.Scrollbar(viewport, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        cards_frame = tk.Frame(canvas, bg='#0b1220')
        item = canvas.create_window((0, 0), window=cards_frame, anchor='nw')
        cards_frame.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        self.cards = {target.binding_id: BatteryCard(cards_frame, target.name, index)
                      for index, target in enumerate(self.targets)}
        controls = tk.Frame(outer, bg='#0b1220')
        controls.pack(fill='x')
        self.refresh_button = tk.Button(controls, text='立即刷新', command=self.refresh, bg='#2563eb', fg='white', relief='flat', padx=14)
        self.refresh_button.pack(side='left')
        tk.Button(controls, text='接口与协议', command=self.open_debug, bg='#1e293b', fg='#e2e8f0', relief='flat', padx=10).pack(side='left', padx=8)
        tk.Button(controls, text='退出', command=self.close, bg='#1e293b', fg='#e2e8f0', relief='flat', padx=14).pack(side='right')
        options = tk.Frame(outer, bg='#0b1220')
        options.pack(fill='x', pady=(12, 0))
        tk.Label(options, text='刷新秒数', bg='#0b1220', fg='#94a3b8', font=('Sans', 9)).pack(side='left')
        self.interval_var = tk.StringVar(value=str(self.interval))
        tk.Spinbox(options, from_=30, to=1800, increment=30, textvariable=self.interval_var, width=6).pack(side='left', padx=8)
        tk.Button(options, text='应用', command=self.set_interval).pack(side='left')
        self.auto_var = tk.BooleanVar()
        tk.Checkbutton(outer, text='登录桌面后启动', variable=self.auto_var, command=self.toggle_autostart,
                       bg='#0b1220', fg='#94a3b8', selectcolor='#1e293b', activebackground='#0b1220',
                       activeforeground='#e2e8f0').pack(anchor='w', pady=(8, 0))
        self.auto_label = tk.Label(outer, text='', bg='#0b1220', fg='#64748b', font=('Sans', 8), anchor='w', wraplength=380)
        self.auto_label.pack(fill='x')
        self._read_autostart()

    def _read_autostart(self):
        try:
            enabled, label = autostart_status()
        except OSError as error:
            enabled, label = False, str(error)
        self.auto_var.set(enabled)
        self.auto_label.config(text=label)

    def notify(self, action, value):
        self.events.put((action, value))
        try:
            os.write(self.pipe_w, b'x')
        except BlockingIOError:
            pass
        except OSError:
            if not self.closing:
                raise

    def _pump(self, *_):
        try:
            while os.read(self.pipe_r, 4096):
                pass
        except BlockingIOError:
            pass
        while True:
            try:
                action, value = self.events.get_nowait()
            except queue.Empty:
                break
            if action == 'quit':
                self.close()
            elif not self.closing:
                if action == 'result':
                    self._result(value[1], value[0])
                elif action == 'show':
                    self.show()
                elif action == 'refresh':
                    self.refresh()
                elif action == 'debug_result':
                    window, text = value
                    window.display_result(text)
                elif action == 'tray_ready':
                    initial = self.bus_name is None
                    self.tray_available, self.bus_name = True, value
                    self.tray.send('update', self.data)
                    if self.args.tray and initial:
                        self.root.withdraw()
                elif action == 'tray_error':
                    self.tray_available = False
                    self.show()
                    self.auto_label.config(text='托盘不可用：' + value)

    def _accept(self, *_):
        try:
            client, _ = self.instance.socket.accept()
        except BlockingIOError:
            return
        if len(self.clients) >= 4:
            client.close()
            return
        client.setblocking(False)
        timeout = self.root.after(2000, lambda: self._drop_client(client))
        self.clients[client] = [bytearray(), timeout]
        self.root.createfilehandler(client, tk.READABLE, self._receive)

    def _drop_client(self, client):
        if client in self.clients:
            self.root.deletefilehandler(client)
            self.root.after_cancel(self.clients.pop(client)[1])
            client.close()

    def _receive(self, client, _):
        try:
            data = client.recv(4096)
            if not data:
                self._drop_client(client)
                return
            buffer = self.clients[client][0]
            buffer.extend(data)
            if len(buffer) > 4096:
                raise ValueError('IPC 请求过长')
            if b'\n' not in buffer:
                return
            request = json.loads(buffer.split(b'\n', 1)[0])
            action = request.get('action')
            if ('targets' in request and request['targets'] != selectors(self.targets)) or ('interval' in request and request['interval'] != self.interval):
                client.sendall(json.dumps({'version': 2, 'error': '已有实例的设备选择或刷新间隔不同；请退出后重启，或在面板中设置间隔'}, ensure_ascii=False).encode() + b'\n')
                self._drop_client(client)
                return
            if action == 'show':
                self.show()
            elif action == 'debug':
                self.show()
                self.open_debug()
            elif action == 'refresh':
                self.refresh()
            elif action == 'quit':
                self.root.after_idle(self.close)
            elif action != 'status':
                raise ValueError('未知命令')
            response = {'pid': os.getpid(), 'visible': self.root.state() != 'withdrawn',
                        'window_id': self.root.winfo_id(),
                        'window_size': [self.root.winfo_width(), self.root.winfo_height()],
                        'tray_available': self.tray_available, 'tray_bus_name': self.bus_name,
                        'version': 2, 'targets': selectors(self.targets),
                        'batteries': self.devices_data, 'reading': self.service.busy(),
                        'interval': self.interval, 'battery': self.data}
            if self.debug_window is not None and self.debug_window.window.winfo_exists():
                window = self.debug_window.window
                response['debug_window_id'] = window.winfo_id()
                response['debug_window_size'] = [window.winfo_width(), window.winfo_height()]
            client.send(json.dumps(response, ensure_ascii=False).encode() + b'\n')
            self._drop_client(client)
        except BlockingIOError:
            return
        except (OSError, ValueError, AttributeError):
            self._drop_client(client)

    def refresh(self):
        if not self.closing:
            self.service.refresh()

    def _result(self, result, binding_id=None):
        key = binding_id or self.primary
        self.devices_data[key] = result
        self.cards[key].render(result)
        if key == self.primary:
            self.data = result
            self.tray.send('update', result)

    def set_interval(self):
        try:
            interval = int(self.interval_var.get())
            save_interval(interval)
            self.service.set_interval(interval)
            self.interval = interval
        except (ValueError, OSError) as error:
            messagebox.showerror('无法保存', str(error), parent=self.root)

    def open_debug(self):
        if self.debug_window is not None and self.debug_window.window.winfo_exists():
            self.debug_window.window.deiconify()
            self.debug_window.window.lift()
            return
        from .debug_panel import DebugPanel
        self.debug_window = DebugPanel(self)

    def toggle_autostart(self):
        try:
            set_autostart(self.auto_var.get())
        except OSError as error:
            messagebox.showerror('无法设置自启', str(error), parent=self.root)
        self._read_autostart()

    def show(self):
        if not self.closing:
            self._read_autostart()
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

    def hide(self):
        if self.tray_available:
            self.root.withdraw()
        else:
            self.close()

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.root.withdraw()
        self.service.close(wait=False)
        self.tray.stop()
        self._finish()

    def _finish(self):
        if self.service.is_alive or self.tray.thread.is_alive():
            self.root.after(25, self._finish)
            return
        for client in list(self.clients):
            self._drop_client(client)
        self.root.deletefilehandler(self.instance.socket)
        self.root.deletefilehandler(self.pipe_r)
        for fd in (self.pipe_r, self.pipe_w):
            os.close(fd)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def run_panel(args):
    if os.geteuid() == 0:
        raise RuntimeError('图形界面必须以普通桌面用户运行')
    try:
        instance = Instance()
    except BlockingIOError:
        parameters = {'targets': selectors(targets_for_args(args))}
        if args.interval is not None:
            parameters['interval'] = args.interval
        response = command('debug' if args.debug_panel else 'show', **parameters)
        if response.get('error'):
            raise RuntimeError(response['error'])
        return 0
    try:
        app = Panel(args, instance)
        app.run()
    finally:
        instance.close()
    return 0
