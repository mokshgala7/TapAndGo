import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent.parent
if str(V6) not in sys.path:
    sys.path.insert(0, str(V6))


@pytest.fixture(scope="session")
def scorer():
    from integration.inference import FraudScorerV6
    return FraudScorerV6.load()
