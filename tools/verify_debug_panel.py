#!/usr/bin/env python3
"""Exercise debug UI without sending arbitrary commands or capturing keypresses."""

from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keyboard_power.debug import decode_calibrated
from keyboard_power.panel import Panel
from keyboard_power.runtime import Instance


def main():
    instance = Instance()
    app = None
    failures = []
    deadline = time.monotonic() + 10
    try:
        args = SimpleNamespace(interval=60, vid='05AC', pid='024F', usb_path=None,
                               tray=False, debug=False, debug_panel=True)
        app = Panel(args, instance)
        def ready():
            try:
                if time.monotonic() > deadline:
                    raise AssertionError('debug acceptance timed out')
                if app.service.busy():
                    app.root.after(50, ready)
                    return
                debug = app.debug_window
                assert debug.window.winfo_exists()
                selection = debug.tree.selection()[0]
                assert debug.tree.bbox(selection), 'selected vendor row not visible'
                sample = bytes.fromhex('2001002700000000000000000000000000000000000000000000000000000048')
                assert decode_calibrated(debug.config(), sample)['percent'] == 39
                debug.feature()
                app.root.after(100, feature_done)
            except Exception as error:
                failures.append(str(error))
                app.close()
        def feature_done():
            try:
                if time.monotonic() > deadline:
                    raise AssertionError('Feature refusal timed out')
                debug = app.debug_window
                if debug.pending:
                    app.root.after(50, feature_done)
                    return
                # Pipe delivery may occur just after the worker exits.
                app._pump()
                assert '没有声明 Feature' in debug.output.get('1.0', 'end')
                debug.listen()
                app.root.after(100, app.close)
            except Exception as error:
                failures.append(str(error))
                app.close()
        app.root.after(100, ready)
        app.run()
        assert not failures, failures
        assert not app.tray.thread.is_alive()
        assert not app.service.is_alive
    finally:
        instance.close()
    assert not instance.path.exists()
    print('debug UI PASS: visible selection, calibrated 39%, undeclared Feature refused, vendor listener cancelled, no worker/IPC remnants')


if __name__ == '__main__':
    main()
