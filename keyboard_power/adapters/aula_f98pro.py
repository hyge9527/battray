"""Reviewed F98Pro adapter; protocol and fd ownership remain in aula.py."""

from .base import BackendResult, ReadContext
from .profiles import F98PRO, match_f98pro
from ..domain.readings import Reading
from ..transport import ResourceBusy


class AulaF98ProAdapter:
    profile = F98PRO

    def match(self, devices):
        return match_f98pro(devices)

    def read(self, devices, context: ReadContext):
        # Revalidate here so direct callers cannot bypass the registry gate.
        match = self.match(devices)
        if not match.automatic_read_allowed:
            raise ValueError(match.reason)
        device = devices[match.index]
        from ..aula import query
        try:
            sample = query(devices, cancel_fd=context.cancel_fd, trace=context.trace)
            now = int(context.clock())
            if sample['percent'] == 0:
                return BackendResult('zero_unverified', '收到 0，但尚未确认是空电量还是未连接占位值', now)
            return BackendResult('ok', '', now, self.profile.display_name,
                                 Reading(sample['percent'], 'AULA FF60/0061 · 32B · 校验和通过', now, now))
        except InterruptedError:
            raise
        except ResourceBusy as error:
            status, reason = 'busy', str(error)
        except PermissionError:
            status, reason = 'permission_denied', f"无权访问 {device['node']}；需要目标厂商接口 ACL/udev 授权"
        except FileNotFoundError:
            status, reason = 'missing_node', f"当前执行环境看不到 {device['node']}，请检查设备节点隔离或重连"
        except TimeoutError as error:
            status, reason = 'timeout', str(error)
        except (OSError, ValueError, RuntimeError) as error:
            status, reason = 'read_failed', str(error)
        return BackendResult(status, reason, int(context.clock()))
