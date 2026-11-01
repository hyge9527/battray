from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class InterfaceIdentity:
    vid: str
    pid: str
    product: str
    interface: str
    bcd_device: str
    descriptor_hex: str
    node: str = ''
    hid_path: str = ''
    usb_path: str = ''

    @classmethod
    def from_mapping(cls, device):
        return cls(**{name: device.get(name) or '' for name in cls.__dataclass_fields__})

    @property
    def descriptor_sha256(self):
        return hashlib.sha256(bytes.fromhex(self.descriptor_hex)).hexdigest()

    @property
    def receiver_key(self):
        # A physical transport resource, not a persistent user/device identity.
        return self.usb_path or self.hid_path


@dataclass(frozen=True)
class DeviceBinding:
    binding_id: str
    profile_id: str
    display_name: str
    receiver_key: str


@dataclass(frozen=True)
class Connection:
    connection_id: str
    generation: int
    receiver_key: str

    def __post_init__(self):
        if not self.connection_id or type(self.generation) is not int or self.generation < 0:
            raise ValueError('connection requires a nonempty ID and nonnegative generation')
