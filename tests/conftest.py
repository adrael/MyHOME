"""Run the suite against the validation backend Home Assistant actually uses.

Home Assistant 2026.9 replaced voluptuous with probatio, which registers a
compatibility shim under the ``voluptuous`` name. The shim compiles nested
schemas differently from the real voluptuous (it never calls an overridden
``Schema.__call__``), which is exactly what broke the config file validator.

The shim is installed when probatio is importable, unless
``MYHOME_VALIDATION_BACKEND=voluptuous`` asks for the real library. Either way
the header of the pytest run says which one is in use.
"""

import os
import sys

_REQUESTED = os.environ.get("MYHOME_VALIDATION_BACKEND", "probatio")

if _REQUESTED == "probatio":
    try:
        import probatio.compat
    except ImportError:
        _BACKEND = "voluptuous (probatio not installed)"
    else:
        assert "voluptuous" not in sys.modules, "voluptuous imported before the shim"
        probatio.compat.install_as_voluptuous()
        _BACKEND = "probatio voluptuous shim"
elif _REQUESTED == "voluptuous":
    _BACKEND = "voluptuous"
else:
    raise RuntimeError(f"MYHOME_VALIDATION_BACKEND={_REQUESTED!r}: expected 'probatio' or 'voluptuous'")


def pytest_report_header(config):  # pylint: disable=unused-argument
    return f"validation backend: {_BACKEND}"
