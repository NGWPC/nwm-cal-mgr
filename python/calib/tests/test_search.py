from typing import TYPE_CHECKING

import pytest
from calib.search import dds

if TYPE_CHECKING:
    from calib.agent import Agent
    from calib.calibration_cathment import CalibrationCatchment
    from calib.meta import CalibrationMeta

"""
    Test suite for calibrtion search algorithms
"""


@pytest.mark.skip(reason="The dds algorithm has been updated. Skipping this test for now.")
@pytest.mark.usefixtures("catchment", "agent")
def test_dds(catchment: "CalibrationCatchment", agent: "Agent") -> None:
    """
    Test dds is callable
    """
    ret = dds(1, 2, catchment, agent)
    assert catchment.best_score == 0.0
    assert catchment.best_params == "2"
