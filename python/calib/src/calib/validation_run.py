import logging
import os
import shutil
from typing import TYPE_CHECKING

import pandas as pd

logger = logging.getLogger(__name__)

from .plot_output import plot_valid_output
from .search import _calc_metrics, _execute
from .utils import complete_msg, pushd

if TYPE_CHECKING:
    pass


import logging

from .configuration import NoCalibModel

logger = logging.getLogger(__name__)


def run_valid_ctrl_best(agent):
    """
    Run validation for control and best runs, or execute single-run validation for NoCalibModel.

    Parameters
    ----------
    agent : Agent
        Agent object containing model and configuration info.
    """
    # Single-execution model (NoCalibModel) validation

    if isinstance(agent.model, NoCalibModel):
        logger.info(
            f"Running validation for NoCalibModel (Single Exec): {agent.run_name}"
        )
        # Execute model run and post-process results
        with pushd(agent.job.workdir):
            logger.info(agent.cmd)
            _execute(agent)
            agent.model.postprocess_single_validation_output(agent)
        logger.info("[NoCalibModel] Validation complete.")
        return

    # -----------------------------------------
    # Regular calibrated model validation
    # -----------------------------------------

    shutil.copy(
        agent.realization_file,
        os.path.join(agent.job.workdir, os.path.basename(agent.realization_file)),
    )

    # read nwm retrospective streamflow if exists
    if agent.run_name != "valid_control":
        if agent.nwmflow_file != "":
            if os.path.exists(agent.nwmflow_file):
                logger.info(
                    f"Read NWM retrospective streamflow simulation from: {agent.nwmflow_file}"
                )
                nwm = pd.read_csv(agent.nwmflow_file)
                nwm.columns = ["value_date", "sim_flow"]
                nwm["value_date"] = pd.DatetimeIndex(nwm["value_date"])
                agent.nwmflow = nwm.set_index("value_date")
            else:
                logger.error(f"File does not exist: {agent.nwmflow_file}")
        else:
            agent.nwmflow = None

    # Handle both grouped and uniform calibrations
    calibration_sets = agent.model.adjustables
    print(f"DEBUG: calibration_objects: {calibration_sets}")
    if not isinstance(calibration_sets, list):
        # Uniform calibration - wrap in list
        calibration_sets = [calibration_sets]

    # Get first evaluatable object
    primary_set = calibration_sets[0]
    evaluatable_objects = _get_evaluatable_objs(primary_set)
    if isinstance(evaluatable_objects, list):
        calibration_object = evaluatable_objects[0]
    else:
        calibration_object = evaluatable_objects

    # Run validation simulation
    with pushd(agent.job.workdir):
        logger.info(f"Running simulation for {agent.run_name}")
        _execute(agent)

    # Calculate metric using first calibration object
    print(f"DEBUG: calibration_object: {calibration_object}")
    with pushd(agent.job.workdir):
        time_period = {
            "calib": primary_set.evaluation_range,
            "valid": primary_set.valid_evaluation_range,
            "full": primary_set.full_evaluation_range,
        }

        outputs = [primary_set.output]
        print(f"DEBUG: outputs={outputs}")
        runs = [agent.run_name]
        if agent.run_name != "valid_control":
            if agent.nwmflow is not None:
                outputs.append(agent.nwmflow)
                runs.append("nwm_retro")

        for out1, run1 in zip(outputs, runs):
            metrics = pd.DataFrame()
            # logger.info(f"Computing metrics for out1 : {out1}, run1: {run1}")
            for key, value in time_period.items():
                result = _calc_metrics(
                    out1,
                    primary_set.observed,
                    value,
                    primary_set.threshold,
                    primary_set.peak_flow_threshold,
                )
                tmp = {**{"run": run1, "period": key}, **result}
                metrics = pd.concat([metrics, pd.DataFrame([tmp])], ignore_index=True)
                metric_out_file = os.path.join(
                    agent.workdir,
                    "{}".format(primary_set.basinID) + "_metrics_{}.csv".format(run1),
                )
                metrics.to_csv(metric_out_file, index=False)

        # Save and move output
        calibration_object.save_valid_output(
            primary_set.basinID,
            agent.run_name,
            agent.valid_path,
            agent.job.workdir,
            agent.valid_path_output,
        )

        # plot the validation plots (for valid_best or validation with alternative parameters)
        if agent.run_name != "valid_control":
            runs = ["valid_control", "valid_best"]
            if agent.nwmflow is not None:
                runs.append("nwm_retro")
            if agent.run_name != "valid_best":
                runs.append(agent.run_name)
            logger.info(f"Generating plots comparing {runs}")

            plot_valid_output(calibration_object, agent, runs, time_period)

        # Indicate completion
        primary_set.write_run_complete_file(agent.run_name, agent.workdir)
        complete_msg(
            primary_set.basinID,
            agent.run_name,
            agent.workdir,
            primary_set.user,
        )


def _get_evaluatable_objs(calibration_object):
    """
    Get a list of evaluatable objects from either a single Adjustable (NgenUniform)
    of a CalibrationSet with nested adjustables (NgenGrouped)
    """
    if hasattr(calibration_object, 'adjustables') and calibration_object.adjustables:
        # CalibrationSet with nested adjustables
        return calibration_object.adjustables
    else:
        # Single Adjustable
        return calibration_object

