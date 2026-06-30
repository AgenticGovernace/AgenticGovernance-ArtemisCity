"""Instruction hierarchy system for multi-scope configuration.

This module provides cascading instruction loading from global, project,
local, and agent-specific scopes.
"""

#  Copyright (c) 2026. Lorem ipsum dolor sit amet, consectetur adipiscing elit.
#  Morbi non lorem porttitor neque feugiat blandit. Ut vitae ipsum eget quam lacinia accumsan.
#  Etiam sed turpis ac ipsum condimentum fringilla. Maecenas magna.
#  Proin dapibus sapien vel ante. Aliquam erat volutpat. Pellentesque sagittis ligula eget metus.
#  Vestibulum commodo. Ut rhoncus gravida arcu.

from .instruction_cache import InstructionCache, get_global_cache, reset_global_cache
from .instruction_loader import InstructionLoader, InstructionScope, InstructionSet

__all__ = [
    "InstructionLoader",
    "InstructionSet",
    "InstructionScope",
    "InstructionCache",
    "get_global_cache",
    "reset_global_cache",
]
