import sys
from unittest.mock import MagicMock

if sys.platform == "win32":
    resource_mock = MagicMock()
    resource_mock.RLIMIT_CPU = 0
    resource_mock.RLIMIT_AS = 1
    resource_mock.error = Exception
    sys.modules["resource"] = resource_mock
