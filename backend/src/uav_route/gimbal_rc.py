"""
Gimbal control via **RC pass-through** channels using MAVLink ``RC_CHANNELS_OVERRIDE``.

This matches the common mapping (verify against your mount / ``MNT_*`` params):

==========  =================  =================
Channel     RC low (≈1100)     RC high (≈1900)
==========  =================  =================
**RC6**     Roll left          Roll right
**RC7**     Pitch **down**     Pitch **up**
**RC8**     Yaw one way        Yaw other way
==========  =================  =================

Neutral / center is typically **1500** μs.

**Examples** (same idea as MAVProxy ``rc`` commands):

- ``rc 6 1100`` — gimbal rolls left
- ``rc 7 1900`` — gimbal pitch upwards (look more forward / horizon)
- ``rc 8 1500`` — gimbal yaw neutral

**Nadir** (camera straight down) uses **pitch down** → RC7 **low** (1100), with roll/yaw at neutral (1500).
"""

from __future__ import annotations

from typing import Any

# Typical stick endpoints (μs PWM). Tune if your TX uses a different range.
RC_LOW = 1100
RC_MID = 1500
RC_HIGH = 1900

# MAVLink: UINT16_MAX means “do not override this channel” for RC_CHANNELS_OVERRIDE.
_CHAN_IGNORE = 65535

# 1-based RC channel numbers on your radio → gimbal axes
CH_ROLL = 6
CH_PITCH = 7
CH_YAW = 8


def pwm_nadir() -> tuple[int, int, int]:
    """Roll level, pitch down (nadir), yaw neutral."""
    return (RC_MID, RC_LOW, RC_MID)


def pwm_neutral() -> tuple[int, int, int]:
    """Level horizon-style neutral on roll / pitch / yaw axes."""
    return (RC_MID, RC_MID, RC_MID)


def pwm_forward_look() -> tuple[int, int, int]:
    """Roll level, pitch up (see ``rc 7 1900`` example), yaw neutral."""
    return (RC_MID, RC_HIGH, RC_MID)


PRESETS: dict[str, tuple[int, int, int]] = {
    "nadir": pwm_nadir(),
    "neutral": pwm_neutral(),
    "forward": pwm_forward_look(),
}


def channels_1_to_8(
    roll_pwm: int | None,
    pitch_pwm: int | None,
    yaw_pwm: int | None,
    *,
    ignore: int = _CHAN_IGNORE,
) -> tuple[int, int, int, int, int, int, int, int]:
    """Build chan1..chan8 for ``rc_channels_override_send``; only 6–8 are set here."""
    ch = [ignore] * 8
    if roll_pwm is not None:
        ch[CH_ROLL - 1] = int(roll_pwm)
    if pitch_pwm is not None:
        ch[CH_PITCH - 1] = int(pitch_pwm)
    if yaw_pwm is not None:
        ch[CH_YAW - 1] = int(yaw_pwm)
    return tuple(ch)  # type: ignore[return-value]


def send_gimbal_rc(
    master: Any,
    roll_pwm: int | None,
    pitch_pwm: int | None,
    yaw_pwm: int | None,
) -> None:
    """Send RC override for gimbal axes on RC6–RC8 only (other channels unchanged)."""
    c1, c2, c3, c4, c5, c6, c7, c8 = channels_1_to_8(roll_pwm, pitch_pwm, yaw_pwm)
    master.mav.rc_channels_override_send(
        master.target_system,
        master.target_component,
        c1,
        c2,
        c3,
        c4,
        c5,
        c6,
        c7,
        c8,
    )


def apply_preset(master: Any, preset: str) -> tuple[int, int, int]:
    """
    Apply a named preset. Known keys: ``nadir``, ``neutral``, ``forward``.

    Returns the (roll, pitch, yaw) PWM tuple that was sent.
    """
    key = preset.strip().lower()
    if key not in PRESETS:
        raise ValueError(f"Unknown gimbal preset {preset!r}; use {sorted(PRESETS)}")
    roll, pitch, yaw = PRESETS[key]
    send_gimbal_rc(master, roll, pitch, yaw)
    return (roll, pitch, yaw)
