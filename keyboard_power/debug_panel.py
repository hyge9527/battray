import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .debug import calibration_template, decode_calibrated, exchange, read_feature, validate_calibration
from .hid import enumerate_hid


class DebugPanel:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('HID 接口与手动标定')
        self.window.geometry('920x720')
        self.pending = False
        self.devices = {}
        top = ttk.Frame(self.window, padding=10)
        top.pack(fill='both', expand=True)
        ttk.Label(top, text='所有接口只读枚举；监听/试发仅允许纯厂商集合。不会扫描未知命令。').pack(anchor='w')
        self.tree = ttk.Treeview(top, columns=('id', 'interface', 'access', 'collections'), show='tree headings', height=7)
        for name, title, width in [('#0', '节点 / 产品', 300), ('id', 'VID:PID', 90),
                                   ('interface', '接口', 40), ('access', '权限', 120), ('collections', 'Usage', 220)]:
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width)
        self.tree.pack(fill='x', pady=8)
        self.tree.bind('<<TreeviewSelect>>', self.inspect)
        ttk.Button(top, text='重新枚举', command=self.reload).pack(anchor='w')
        tabs = ttk.Notebook(top)
        tabs.pack(fill='both', expand=True, pady=8)
        reports, calibration = ttk.Frame(tabs), ttk.Frame(tabs)
        tabs.add(reports, text='接口与原始报告')
        tabs.add(calibration, text='JSON 手动标定')
        self.output = tk.Text(reports, height=12, wrap='word')
        self.output.pack(fill='both', expand=True)
        actions = ttk.Frame(reports)
        actions.pack(fill='x', pady=6)
        ttk.Label(actions, text='Report ID').pack(side='left')
        self.report_id = tk.StringVar(value='0')
        ttk.Entry(actions, textvariable=self.report_id, width=6).pack(side='left', padx=5)
        ttk.Button(actions, text='读取 Feature', command=self.feature).pack(side='left')
        ttk.Button(actions, text='监听厂商 Input 2 秒', command=self.listen).pack(side='left', padx=6)
        ttk.Label(reports, text='完整 hidraw 写缓冲区（十六进制，首字节为 Report ID / 00；不会自动发送）').pack(anchor='w')
        self.request = tk.StringVar()
        ttk.Entry(reports, textvariable=self.request).pack(fill='x')
        ttk.Button(reports, text='预览并手动发送一次', command=self.send).pack(anchor='w', pady=5)
        self.editor = tk.Text(calibration, wrap='word')
        self.editor.pack(fill='both', expand=True)
        self.sample = tk.StringVar(value='20 01 00 27 ' + '00 ' * 27 + '48')
        ttk.Label(calibration, text='输入完整报告样本进行换算（偏移含编号报告的 ID 字节）').pack(anchor='w')
        ttk.Entry(calibration, textvariable=self.sample).pack(fill='x')
        controls = ttk.Frame(calibration)
        controls.pack(fill='x', pady=5)
        ttk.Button(controls, text='校验并换算', command=self.decode).pack(side='left')
        ttk.Button(controls, text='保存 JSON', command=self.save).pack(side='left', padx=6)
        ttk.Button(controls, text='加载 JSON', command=self.load).pack(side='left')
        self.calibration_result = ttk.Label(calibration, text='保存配置不会自动发送其中的请求；用原始报告验证字段后再试发。', wraplength=850)
        self.calibration_result.pack(anchor='w')
        self.reload()

    def reload(self):
        self.tree.delete(*self.tree.get_children())
        self.devices = {d['node']: d for d in enumerate_hid()}
        for node, device in self.devices.items():
            self.tree.insert('', 'end', iid=node, text=node + ' · ' + device['name'],
                             values=(device['vid'] + ':' + device['pid'], device['interface'],
                                     device['access'], ', '.join(device.get('collections', []))))
        from .adapters.profiles import match_f98pro
        candidates = list(self.devices.values())
        match = match_f98pro(candidates)
        preferred = candidates[match.index]['node'] if match.automatic_read_allowed else None
        if preferred:
            self.tree.selection_set(preferred)
            self.tree.see(preferred)
            self.inspect()

    def selected(self):
        selection = self.tree.selection()
        if not selection:
            raise ValueError('先选择接口')
        return self.devices[selection[0]]

    def inspect(self, *_):
        try:
            device = self.selected()
            self.output.delete('1.0', 'end')
            self.output.insert('end', json.dumps(device, ensure_ascii=False, indent=2))
            if device.get('descriptor_hex'):
                self.editor.delete('1.0', 'end')
                template = calibration_template(device)
                self.editor.insert('end', json.dumps(template, ensure_ascii=False, indent=2))
                self.request.set(template['request_buffer_hex'])
        except ValueError:
            pass

    def start(self, operation):
        if self.pending:
            messagebox.showinfo('读取中', '请等待当前调试操作完成', parent=self.window)
            return
        self.pending = True
        def completed(result, error):
            text = '失败：' + str(error) if error is not None else result
            self.app.notify('debug_result', (self, text))
        try:
            self.app.service.debug(lambda cancel: operation(cancel.read_fd), completed)
        except Exception:
            self.pending = False
            raise

    def display_result(self, text):
        self.pending = False
        if self.window.winfo_exists():
            self.output.insert('end', '\n\n' + str(text) + '\n')
            self.output.see('end')

    def feature(self):
        try:
            from .adapters.standard_hid import feature_diagnostic
            device, rid = dict(self.selected()), int(self.report_id.get(), 0)
            def read(cancel_fd):
                raw_hex = read_feature(device['node'], rid)
                try:
                    return feature_diagnostic(device, rid, raw_hex)
                except ValueError as error:
                    return 'Feature: ' + raw_hex + '\n标准字段解析未通过：' + str(error)
            self.start(read)
        except ValueError as error:
            messagebox.showerror('无法读取', str(error), parent=self.window)

    def listen(self):
        try:
            node = self.selected()['node']
            self.start(lambda cancel_fd: '\n'.join(exchange(node, duration=2, cancel_fd=cancel_fd)) or '2 秒内未收到厂商报告')
        except ValueError as error:
            messagebox.showerror('无法监听', str(error), parent=self.window)

    def send(self):
        try:
            node, buffer = self.selected()['node'], bytes.fromhex(self.request.get())
            from .debug import validate_write
            validate_write(self.selected(), buffer)
            if messagebox.askokcancel('确认一次手动发送', node + '\n' + buffer.hex(' ') + '\n\n未知命令可能改变设备设置。仅在已确认报文含义时发送。', parent=self.window):
                self.start(lambda cancel_fd: '\n'.join(exchange(node, buffer, cancel_fd=cancel_fd)) or '已发送，无回复')
        except ValueError as error:
            messagebox.showerror('无法发送', str(error), parent=self.window)

    def config(self):
        return validate_calibration(json.loads(self.editor.get('1.0', 'end')))

    def decode(self):
        try:
            result = decode_calibrated(self.config(), bytes.fromhex(self.sample.get()))
            self.calibration_result.config(text=json.dumps(result, ensure_ascii=False))
        except (ValueError, KeyError) as error:
            self.calibration_result.config(text='校验失败：' + str(error))

    def save(self):
        try:
            config = self.config()
            path = filedialog.asksaveasfilename(parent=self.window, defaultextension='.json', initialfile='keyboard-profile.json')
            if path:
                from pathlib import Path
                Path(path).write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
        except (ValueError, OSError) as error:
            messagebox.showerror('无法保存', str(error), parent=self.window)

    def load(self):
        path = filedialog.askopenfilename(parent=self.window, filetypes=[('JSON', '*.json')])
        if path:
            try:
                from pathlib import Path
                text = Path(path).read_text()
                validate_calibration(json.loads(text))
                self.editor.delete('1.0', 'end')
                self.editor.insert('end', text)
            except (ValueError, OSError) as error:
                messagebox.showerror('无法加载', str(error), parent=self.window)
