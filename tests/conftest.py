import pytest

from uniassist import mock
from uniassist.timeutil import get_tz
from uniassist.tools import Context


@pytest.fixture
def tz():
    return get_tz()


@pytest.fixture
def ctx(tz):
    return Context(mock.mock_canvas(tz), mock.mock_schedule(tz), mock.mock_programme(),
                   lambda: mock.mock_now(tz))
