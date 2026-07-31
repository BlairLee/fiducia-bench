"""Arm harness: one class per architecture, over the shared tool layer.

Arms differ ONLY in orchestration and context assembly — never in what a tool does or
what the environment records. That is what makes a difference between arms attributable
to decomposition rather than to the instrument.
"""
from .base import Arm, ComponentContext, blocked, stamp
from .d0 import D0Arm
from .d1 import D1Arm
from .d2 import D2Arm

ARMS = {"D0": D0Arm, "D1": D1Arm, "D2": D2Arm}

__all__ = ["Arm", "ARMS", "ComponentContext", "D0Arm", "D1Arm", "D2Arm",
           "blocked", "stamp"]
