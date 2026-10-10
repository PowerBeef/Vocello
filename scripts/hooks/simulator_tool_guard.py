#!/usr/bin/env python3
"""Supplementary physical-device-only guard for canonical MCP tool names."""
import json
import re
import sys

try:
    name = str(json.load(sys.stdin).get("tool_name", "")).lower()
except (ValueError, TypeError, AttributeError):
    raise SystemExit(0)
if re.search(r"(?:^|__)(?:.*_sim|.*_simulator|simulator_.*|simctl)(?:$|__)", name):
    print("Physical iPhone only: use repository device scripts; MCP native UI driving is unsupported.",
          file=sys.stderr)
    raise SystemExit(2)
