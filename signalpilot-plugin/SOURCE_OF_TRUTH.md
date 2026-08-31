# SignalPilot Plugin Source of Truth

This directory is the canonical plugin source shipped in SignalPilot notebook
runtime images.

It was promoted from `benchmark/signalpilot-plugin/`, which is the current
validated benchmark plugin state. Runtime builds must read this directory
directly. The outdated `plugin/` Git submodule was removed and must not be
restored as a runtime source.

When benchmark changes are accepted for production, copy the validated files
here, review the diff, run the plugin checks, and rebuild the notebook image.
Generated files such as `__pycache__/` and `*.pyc` do not belong here.
