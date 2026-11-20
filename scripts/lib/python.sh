#!/usr/bin/env bash
# Select the repository's Python for a shell entry point and its children.
#
# Sourced by scripts/dev.sh, scripts/check_project_inputs.sh and the native
# lane drivers (macos_test.sh, ui_test.sh, ios_device.sh). The bare
# `python3` of the caller's shell may lack the pinned test packages (pytest,
# pytest-xdist, numpy); scripts/select_python.py picks an already-installed
# interpreter that has them, and scripts/lib/python-bin/python3 keeps every
# `python3` child of this shell on it. Nothing is installed and no host setting
# changes. An explicit VOCELLO_PYTHON never falls back to another interpreter.

# shellcheck shell=bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "error: scripts/lib/python.sh must be sourced" >&2
    exit 1
fi

# vocello_use_selected_python <repository root>
# Exports VOCELLO_PYTHON and puts the repository shim first on PATH.
vocello_use_selected_python() {
    local root="$1" selected shim_dir
    shim_dir="$root/scripts/lib/python-bin"
    if ! selected="$(python3 "$root/scripts/select_python.py")"; then
        return 1
    fi
    VOCELLO_PYTHON="$selected"
    export VOCELLO_PYTHON
    case "$PATH" in
        "$shim_dir"|"$shim_dir:"*) ;;
        *) export PATH="$shim_dir:$PATH" ;;
    esac
}
