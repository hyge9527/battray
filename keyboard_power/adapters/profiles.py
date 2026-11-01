"""Reviewed facts shared by production, the lab and installation helpers."""

from ..domain.matching import DeviceProfile, match_profile


F98PRO = DeviceProfile(
    profile_id='aula-f98pro-2g', display_name='AULA F98Pro',
    vid='05AC', pid='024F', product='2.4G Dongle', interface='03',
    descriptor_hex='0660ff0961a1010962150026ff009520750881020963150026ff00952075089102c0',
    supported_revisions=frozenset({'0121'}),
)


def match_f98pro(devices):
    return match_profile(F98PRO, devices)
