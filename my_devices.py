#!/usr/bin/env python3
"""Ubuntu battery CLI: diagnostics, verified reads and explicit HID lab actions."""

import argparse
import json
import sys

from keyboard_power.diagnostics import battery_result, environment, read_battery, snapshot


def hex_id(value):
    try:
        result = int(value, 16)
    except ValueError:
        raise argparse.ArgumentTypeError('需要十六进制 VID/PID') from None
    if not 0 <= result <= 0xffff:
        raise argparse.ArgumentTypeError('VID/PID 超出 16 位范围')
    return f'{result:04X}'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Ubuntu 无线设备电量工具（标准库 + ctypes；当前已验证 F98Pro）')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--once-all', action='store_true', help='读取配置中所有绑定设备，输出 version=2 JSON')
    mode.add_argument('--check-config', metavar='FILE', help='离线校验设备绑定文件，不访问设备')
    mode.add_argument('--set-targets', metavar='FILE', help='显式保存绑定文件供下次面板/自启使用')
    mode.add_argument('--clear-targets', action='store_true', help='显式清除已保存绑定，恢复默认设备')
    mode.add_argument('--onboard', action='store_true', help='只读发现、档案匹配与权限指引，不发送设备命令')
    mode.add_argument('--once', action='store_true', help='读取系统公开值或本机已验证的 F98Pro 电量；失败返回 2')
    mode.add_argument('--list-devices', action='store_true', help='列出全部 HID 接口和报告能力，不发送命令')
    mode.add_argument('--diagnose', action='store_true', help='检查环境、目标接口及系统电量来源')
    mode.add_argument('--probe-aula', action='store_true', help='查看一次原始 AULA 查询样本，仍返回 2；正常电量读取用 --once')
    mode.add_argument('--panel', action='store_true', help='打开简洁面板（默认）')
    mode.add_argument('--debug-panel', action='store_true', help='打开面板与 HID 接口/协议调试窗口')
    mode.add_argument('--tray', action='store_true', help='启动后隐藏到可用托盘')
    mode.add_argument('--status', action='store_true', help='获取运行实例状态')
    mode.add_argument('--refresh', action='store_true', help='请求运行实例立即刷新')
    mode.add_argument('--quit', action='store_true', help='退出运行实例')
    mode.add_argument('--install-desktop', action='store_true', help='显式安装桌面符号链接及项目启动器')
    mode.add_argument('--autostart', choices=('on', 'off', 'status'), help='显式设置/查看登录自启')
    mode.add_argument('--listen', metavar='DEVICE', help='显式监听纯厂商接口，最长 10 秒')
    mode.add_argument('--read-feature', metavar='DEVICE', help='显式转储描述符声明的 Feature Report')
    mode.add_argument('--send-report', metavar='HEX', help='向 --device 手动试发一次完整 hidraw 缓冲区（包含 ID/00 前缀）')
    mode.add_argument('--decode-report', metavar='HEX', help='用 --profile JSON 离线解析报告，不访问设备')
    parser.add_argument('--targets', dest='targets_config', metavar='FILE', help='本次面板或 --once-all 使用的设备绑定文件')
    parser.add_argument('--vid', type=hex_id, default='05AC')
    parser.add_argument('--pid', type=hex_id, default='024F')
    parser.add_argument('--usb-path', help='有多个相同 VID/PID 接收器时，选择枚举结果中的 usb_path')
    parser.add_argument('--json', action='store_true', help='JSON 格式标准输出；不会创建文件')
    parser.add_argument('--debug', action='store_true', help='诊断细节写入标准错误，不创建日志')
    parser.add_argument('--interval', type=int, help='面板刷新间隔，30～1800 秒')
    parser.add_argument('--device', help='手动试发所选 /dev/hidrawN（不会自动扫描）')
    parser.add_argument('--report-id', type=lambda x: int(x, 0), default=0, help='Feature Report ID（十进制或 0x 前缀）')
    parser.add_argument('--duration', type=float, default=2, help='调试监听秒数，0.1～10')
    parser.add_argument('--profile', help='离线手动标定 JSON 路径；不会自动发送其中请求')
    args = parser.parse_args(argv)
    tokens = sys.argv[1:] if argv is None else argv
    args.selection_explicit = any(token.split('=', 1)[0] in ('--vid', '--pid', '--usb-path') for token in tokens)
    args.use_saved_targets = True
    if args.targets_config and args.selection_explicit:
        parser.error('--targets 不能同时使用 --vid/--pid/--usb-path')
    incompatible_targets_mode = any((args.once, args.list_devices, args.diagnose, args.probe_aula,
                                     args.status, args.refresh, args.quit, args.install_desktop,
                                     args.autostart, args.listen, args.read_feature, args.send_report,
                                     args.decode_report, args.check_config, args.set_targets,
                                     args.clear_targets, args.onboard))
    if args.targets_config and incompatible_targets_mode:
        parser.error('--targets 仅用于面板或 --once-all，单设备读取仍使用 --once --vid/--pid/--usb-path')
    if args.check_config or args.set_targets or args.clear_targets:
        from keyboard_power.config.bindings import bindings_document, load_bindings
        if args.clear_targets:
            from keyboard_power.config.store import update
            from keyboard_power.settings import settings_path
            update(settings_path(), clear_bindings=True)
            print('已清除保存的设备绑定；下次启动恢复默认设备')
        else:
            targets = load_bindings(args.check_config or args.set_targets)
            if args.set_targets:
                from keyboard_power.config.store import update
                from keyboard_power.settings import settings_path
                update(settings_path(), targets=targets)
            print(json.dumps(bindings_document(targets), ensure_ascii=False, indent=2))
        return 0
    if args.once_all:
        from keyboard_power.application.service import ApplicationService
        from keyboard_power.application.targets import targets_for_args
        service = ApplicationService()
        try:
            results = {target.binding_id: service.read_once(target) for target in targets_for_args(args)}
        finally:
            service.close()
        print(json.dumps({'version': 2, 'devices': results}, ensure_ascii=False))
        return 0 if all(result['status'] == 'ok' for result in results.values()) else 2
    if args.interval is not None and not 30 <= args.interval <= 1800:
        parser.error('--interval 必须为 30～1800 秒')
    if args.listen or args.read_feature or args.send_report or args.decode_report:
        from keyboard_power.debug import decode_calibrated, exchange, read_feature
        if args.decode_report:
            if not args.profile:
                parser.error('--decode-report 需要 --profile')
            from pathlib import Path
            print(json.dumps(decode_calibrated(json.loads(Path(args.profile).read_text()), bytes.fromhex(args.decode_report)), ensure_ascii=False))
        elif args.read_feature:
            from keyboard_power.application.service import ApplicationService
            print(ApplicationService().run_lab_once(lambda cancel: read_feature(args.read_feature, args.report_id)))
        else:
            if args.send_report and not args.device:
                parser.error('--send-report 需要 --device')
            from keyboard_power.application.service import ApplicationService
            reports = ApplicationService().run_lab_once(lambda cancel: exchange(
                args.listen or args.device, bytes.fromhex(args.send_report) if args.send_report else None,
                args.duration, cancel_fd=cancel.read_fd))
            print('\n'.join(reports) or '未收到厂商报告')
        return 0
    if args.status or args.refresh or args.quit:
        from keyboard_power.runtime import command
        print(json.dumps(command('status' if args.status else 'refresh' if args.refresh else 'quit'), ensure_ascii=False))
        return 0
    if args.install_desktop:
        from keyboard_power.settings import install_desktop
        print('\n'.join(install_desktop()))
        return 0
    if args.autostart:
        from keyboard_power.settings import autostart_status, set_autostart
        if args.autostart != 'status':
            set_autostart(args.autostart == 'on')
        print(autostart_status()[1])
        return 0
    if not (args.once or args.list_devices or args.diagnose or args.probe_aula or args.onboard):
        from keyboard_power.panel import run_panel
        return run_panel(args)
    if args.once:
        def trace(label, data):
            print(f'{label}: {data.hex(" ")}', file=sys.stderr)
        result = read_battery(args.vid, args.pid, args.usb_path, trace=trace if args.debug else None)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        elif result['percent'] is not None:
            print(f"无线键盘：{result['percent']:g}% [{result['status']}] 来源：{result['source']} {result['reason']}")
        else:
            print(f"无线键盘：未知 [{result['status']}] {result['reason']}")
        return 0 if result['status'] == 'ok' else 2
    info = snapshot(args.vid, args.pid, args.usb_path, all_devices=args.list_devices)
    if args.onboard:
        from keyboard_power.application.onboarding import assess
        print(json.dumps(assess(info), ensure_ascii=False, indent=2))
        return 0
    result = battery_result(info)
    if args.probe_aula:
        from keyboard_power.aula import query
        def trace(label, data):
            print(f'{label}: {data.hex(" ")}', file=sys.stderr)
        try:
            from keyboard_power.application.service import ApplicationService
            result = ApplicationService().run_lab_once(lambda cancel: query(
                info['devices'], trace=trace if args.debug else None, cancel_fd=cancel.read_fd))
        except (OSError, ValueError) as error:
            result = {'status': 'probe_failed', 'percent': None, 'reason': str(error)}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"AULA F98Pro：{result['percent'] if result['percent'] is not None else '未知'} [{result['status']}] {result['reason']}")
        return 2  # A raw sample is not a validated percentage yet.
    if args.diagnose:
        info['environment'] = environment()
    if args.debug:
        print(json.dumps(info, ensure_ascii=False, indent=2), file=sys.stderr)
    if args.list_devices:
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            for d in info['devices']:
                print(f"{d['node']} {d['vid']}:{d['pid']} if={d['interface']} {d['name']} [{d['access']}]")
                print(f"  usb_path={d['usb_path']} collections={','.join(d.get('collections', []))}")
                for report in d.get('reports', []):
                    buffer = next((f'{k}={v}' for k, v in report.items() if k.endswith('_bytes') and k != 'payload_bytes'), '')
                    print(f"  {report['type']:7} ID={report['report_id']:02X} payload={report['payload_bytes']}B {buffer}")
                if d.get('descriptor_error'):
                    print('  描述符错误：' + d['descriptor_error'])
                print(f"  标准电量字段：{len(d.get('battery_fields', []))}")
        return 0
    if args.diagnose:
        print(json.dumps({**info, 'battery': result}, ensure_ascii=False, indent=2))
        return 0



if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, RuntimeError, ValueError, ImportError) as error:
        if '--debug' in sys.argv:
            raise
        print('无法完成：' + str(error), file=sys.stderr)
        raise SystemExit(2)
