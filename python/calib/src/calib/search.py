"""
This module contains functions to perform parameter optimization using different algorithms.

@author: Nels Frazer, Xia Feng
"""

import glob
import logging
import numbers
import os
import subprocess
import copy
from datetime import datetime
from functools import partial
from pathlib import Path
from math import log
from multiprocessing import pool
from typing import TYPE_CHECKING, Dict, Optional, Tuple, Union, List

import numpy as np  # type: ignore
import pandas as pd  # type: ignore
from mswm.edit_config import create_valid_realization_file

from .gwo_global_best import GlobalBestGWO
from .metric_functions import calculate_all_metrics, treat_values
from .plot_output import plot_calib_output, plot_cost_func
from .utils import complete_msg, pushd, report_to_ngencerf

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

if TYPE_CHECKING:
    from calib import Adjustable, Evaluatable
    from calib.agent import Agent


"""Global private iteration counter

This counter is used by PSO search so that iteration information can be captured
and recorded from within a generic functional representation of an abstract model
managed by a calibration agent.
"""
__iteration_counter = 1


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


def _execute(meta: "Agent", i: int = None) -> None:
    """Execute model run via BMI.

    Parameters
    ----------
    meta : Agent object
    i : Current iteration, default None

    """

    # This is a critical file used by the server to identify which worker goes with which validation run
    if i is None:
        # Only do this for validation jobs
        with open(os.path.join(meta.job.workdir, "worker_id.txt"), "w") as id_file:
            id_file.write(f"{meta.run_name}")

    if meta.job.log_file is None:
        subprocess.check_call(
            meta.cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=True,
            cwd=meta.job.workdir,
        )
    else:
        run_log_file = str(meta.job.log_file)
        if i is not None:
            with open(run_log_file, "w") as log_file:
                log_file.write("------ Iteration = {}".format(i) + " ------\n")
        with open(run_log_file, "a+") as log_file:
            subprocess.check_call(
                meta.cmd,
                stdout=log_file,
                stderr=log_file,
                shell=True,
                cwd=meta.job.workdir,
            )


def _calc_metrics(
    simulated_hydrograph: pd.Series,
    observed_hydrograph: pd.Series,
    eval_range: Tuple[datetime, datetime] = None,
    threshold: Optional[float] = None,
    peak_flow_threshold: Optional[float] = 90.0,
) -> Dict[str, float]:
    """Calculate statistical metrics.

    Parameters
    ----------
    simulated_hydrograph : Time series of simulated streamflow
    observed_hydrograph : Time series of observed streamflow
    eval_range : Evaluation time period for calibration run
    threshold : Streamflow threshold (m3/s)for calculating categorical scores
    peak_flow_threshold : Peak flow threshold (in percentile) for calculating event-based metrics

    Returns
    ----------
    Dictionary of metrics

    """
    df = pd.merge(
        simulated_hydrograph, observed_hydrograph, left_index=True, right_index=True
    )
    if df.empty:
        logger.warning("Cannot compute objective function, do time indicies align?")
    if eval_range:
        df = df.loc[eval_range[0]:eval_range[1]]

    df.reset_index(inplace=True)

    df = treat_values(df, remove_neg=True, remove_na=True, replace_zero=True)

    # reset the time index (needed for calculation of event-based metrics)
    df.set_index(df.columns[0], inplace=True)

    obsflow = df["obs_flow"]
    simflow = df["sim_flow"]

    return calculate_all_metrics(
        obsflow, simflow, threshold, peak_flow_threshold / 100.0
    )


def _evaluate(
    i: int,
    calibration_object: Union["Evaluatable", List["Evaluatable"]],
    agent: "Agent",
    first_iter_for_agent: bool,
    info: bool = False,
) -> float:
    """Calculate objective function and evaluation metrics.
    Save calibration output and generate plots during iteration.

    parameters
    ----------
    i : current iteration
    calibration_object : Adjustable object or list of CalibrationSet objects
    agent : Agent object
    first_iter_for_agent: whether it is first iteration for the agent (for reporting to the server)
       (note first agent starts iteration 0 and the rest start from iteration 1 for GWO & PSO)
    info : whether to print objective, best objective and best parameter to screen, default False

    Returns
    ----------
    Objection funciton at current iteration

    """
    # Handle list of calibration sets for grouped strategy
    if isinstance(calibration_object, list):
        calibration_sets = calibration_object
        primary_obj = calibration_sets[0]
    else:
        calibration_sets = [calibration_object]
        primary_obj = calibration_object

    # Calculate objective function and metrics using first calibration set
    metrics = _calc_metrics(
        primary_obj.output,
        primary_obj.observed,
        primary_obj.evaluation_range,
        primary_obj.threshold,
        primary_obj.peak_flow_threshold,
    )

    #  Handle single-run execution output writing for NoCalibModel
    if agent.run_single_iteration:
        primary_obj.write_iteration_outputs(agent, metrics, metrics["objFunVal"])
        return metrics

    # get objective function value from metrics
    metric_objective_function = metrics[primary_obj.objective.value.upper()]

    # objective function grouping
    obj_group1 = ["kge", "nse", "nnse", "nselog", "corr", "csi", "pod"]
    obj_group2 = ["rmse", "mae", "rsr", "far", "pkbias", "pkte", "evbias"]
    obj_group3 = ["pbias", "lseg_fdc", "hseg_fdc"]

    # determine objective function string for plots axis label based on target and objective function
    obj_func = calibration_object.eval_params.objective
    if obj_func in obj_group1:
        calibration_object.objfunc_str = (
            "1-" + obj_func.upper()
            if calibration_object.target == "min"
            else obj_func.upper()
        )
    elif obj_func in obj_group2:
        calibration_object.objfunc_str = (
            obj_func.upper()
            if calibration_object.target == "min"
            else "-" + obj_func.upper()
        )
    elif obj_func in obj_group3:
        calibration_object.objfunc_str = (
            "abs(" + obj_func.upper() + ")"
            if calibration_object.target == "min"
            else "-abs(" + obj_func.upper() + ")"
        )
    else:
        msg = f"Objective function {obj_func} is not supported"
        logger.error(msg)
        raise Exception(msg)

    # Ensure objective function is a valid numeric value
    if not isinstance(metric_objective_function, numbers.Number) or np.isnan(
        metric_objective_function
    ):
        if primary_obj.target == "min":
            score = 1e10  # use large finite value instead of Inf (to avoid potential issues with some optimizers like GWO and PSO)
            logger.warning(
                "Objective function invalid for this iteration; set score to large value for minimization"
            )
        elif primary_obj.target == "max":
            score = -1e10  # use small finite value instead of -Inf (to avoid potential issues with some optimizers like GWO and PSO)
            logger.warning(
                "Objective function invalid for this iteration; set score to small value for maximization"
            )
        else:
            raise Exception(
                f"Optimization target can only be min or max. {primary_obj.target} is not supported"
            )
    else:

        if primary_obj.eval_params.objective in obj_group1:
            score = (
                1 - metric_objective_function
                if primary_obj.target == "min"
                else metric_objective_function
            )
        elif primary_obj.eval_params.objective in obj_group2:
            score = (
                metric_objective_function
                if primary_obj.target == "min"
                else 1 - metric_objective_function
            )
        elif primary_obj.eval_params.objective in obj_group3:
            score = (
                abs(metric_objective_function)
                if primary_obj.target == "min"
                else 1 - abs(metric_objective_function)
            )
        else:
            raise Exception(
                primary_obj.eval_params.objective + " is not supported for objective function"
            )

    # Update based on latest objective function and write log files
    primary_obj.update(i, score, log=True, algorithm=agent.algorithm)
    if info:
        logger.info(
            "Current score {}\nBest score {}".format(
                score, primary_obj.best_score
            )
        )
        logger.info(
            "Best parameters at iteration {}".format(primary_obj.best_params)
        )

    # Save metrics
    primary_obj.write_metric_iter_file(i, score, metrics)

    # Save params - combine from all groups into single file
    combined_params = []
    for cal_set in calibration_sets:
        combined_params.append(cal_set.adjustables[0].df[[str(i), "param"]])
    combined_params_df = pd.concat(combined_params, ignore_index=True)
    primary_obj.write_param_iter_file(i, combined_params_df)

    # Save output
    primary_obj.save_calib_output(
        i,
        str(primary_obj.output_iter_file),
        str(primary_obj.last_output_file),
        agent.output_iter_path,
        agent.job.workdir,
        agent.calib_path_output,
        primary_obj.save_output_iter_flag,
    )

    # make sure output csv for best iteration is saved at first iteration
    if i == 0:
        primary_obj.save_best_output(
            str(primary_obj.best_output_file), True
        )
    else:
        primary_obj.save_best_output(
            str(primary_obj.best_output_file), primary_obj.best_save_flag
        )

    # Save global best cost, and plot
    if agent.algorithm != "dds":
        cost_iter_file = primary_obj.write_cost_iter_file(i, agent.workdir)
        # if len(glob.glob('*.log'))==1:   #comment out plot_cost_func here since it is also called right below
        #    plot_cost_func(calibration_object, agent, cost_iter_file, agent.algorithm, calib_iter=True)

    # Plot metrics, parameters and output
    if len(glob.glob("*.log")) == 1 and i % primary_obj.save_plot_iter_freq == 0:
        plot_calib_output(i, primary_obj, agent)

    # Save last iteration
    primary_obj.write_last_iteration(i)

    # report info back to server if running from ngenCERF GUI
    report_to_ngencerf(agent, iteration=i, first_iter=first_iter_for_agent)

    return score


def dds_update(
    iteration: int,
    inclusion_probability: float,
    calibration_object: "Adjustable",
    agent: "Agent",
) -> None:
    """Dynamically dimensioned search optimization algorithm.

    parameters
    ----------
    iteration : Current iteration
    inclusion_probability : Probability of each parameter included in neighborhood
    calibration_object : Adjustable object
    agent : Agent object

    """
    logger.info("inclusion probability: {}".format(inclusion_probability))
    neighborhood = calibration_object.variables.sample(frac=inclusion_probability)
    if neighborhood.empty:
        neighborhood = calibration_object.variables.sample(n=1)

    # Generate new parameter set by perturbng the best parameters
    calibration_object.df[str(iteration)] = calibration_object.df[agent.best_params].copy()
    for n in neighborhood:
        new = calibration_object.df.loc[
            n, agent.best_params
        ] + calibration_object.df.loc[n, "sigma"] * np.random.normal(0, 1)
        lower = calibration_object.df.loc[n, "min"]
        upper = calibration_object.df.loc[n, "max"]
        if new < lower:
            new = lower + (lower - new)
            if new > upper:
                new = lower
        elif new > upper:
            new = upper - (new - upper)
            if new < lower:
                new = upper
        calibration_object.df.loc[n, str(iteration)] = new

    # Fill parameters for all formulations with unique parameter
    calibration_object.df_fill(iteration)

    # Update realization config file with new parameters
    agent.update_config(
        iteration,
        calibration_object.adf[[str(iteration), "param", "model"]],
        calibration_object.id,
    )


def dds(
    start_iteration: int,
    iterations: int,
    calibration_object: "Evaluatable",
    agent: "Agent",
) -> None:
    """Perform parameter optimization using DDS algorithm.

    Parameters
    ----------
    start_iteration : starting iteration
    iterations : total number of iterations
    agent : Agent object

    """

    if iterations < 2:
        raise ValueError(
            "iterations must be >= 2 for DDS with calibratable parameters."
        )

    if start_iteration > iterations:
        raise (ValueError("start_iteration must be <= iterations"))

    init = start_iteration - 1 if start_iteration > 0 else start_iteration
    neighborhood_size = agent.parameters.get("neighborhood", 0.2)
    calibration_object.df["sigma"] = neighborhood_size * (
        calibration_object.df["max"] - calibration_object.df["min"]
    )
    agent.update_config(
        init,
        calibration_object.df[[str(init), "param", "model"]],
        calibration_object.id,
    )
    # Write realization file with all updated parameters
    agent.model.strategy.write_realization_file(path=Path(agent.job.workdir))

    # Produce baseline simulation output using the default parameter set
    if start_iteration == 0:
        if calibration_object.output is None:
            logger.info("Running {} to produce initial simulation".format(agent.cmd))
            agent.update_config(
                start_iteration,
                calibration_object.df[[str(start_iteration), "param", "model"]],
                calibration_object.id,
            )
            # Write realization file with all updated parameters
            agent.model.strategy.write_realization_file(path=Path(agent.job.workdir))
            _execute(agent, start_iteration)
        with pushd(agent.job.workdir):
            _evaluate(
                0, calibration_object, agent, first_iter_for_agent=True, info=True
            )
        calibration_object.check_point(agent.job.workdir)
        start_iteration += 1

    for i in range(start_iteration, iterations + 1):
        # Calculate probability of inclusion
        inclusion_probability = 1 - log(i) / log(iterations)
        dds_update(i, inclusion_probability, calibration_object, agent)
        # Write realization file with all updated parameters
        agent.model.strategy.write_realization_file(path=Path(agent.job.workdir))
        # Run cmd
        logger.info("Running {} for iteration {}".format(agent.cmd, i))
        _execute(agent, i)
        with pushd(agent.job.workdir):
            _evaluate(i, calibration_object, agent, first_iter_for_agent=False)
        calibration_object.check_point(agent.job.workdir)


def single_exec(agent: "Agent") -> None:
    """Perform parameter optimization using DDS or single-run for NoCalibModel."""
    # from .configuration import NoCalibModel
    import shutil

    from .search import _execute
    from .utils import complete_msg

    # if isinstance(agent.model, NoCalibModel):
    if agent.run_single_iteration:
        logger.info(
            "[NoCalibModel] Detected NoCalibModel (single-run), executing single-run workflow."
        )
        from pathlib import Path

        # Run model
        realization_src = Path(agent.realization_file)
        realization_dst = Path(agent.job.workdir) / realization_src.name
        if not realization_dst.exists():
            logger.debug(
                f"Copying realization file {realization_src} -> {realization_dst}"
            )
            shutil.copy(realization_src, realization_dst)

        # Update internal realization path
        agent.model.realization = realization_dst

        # Build and run ngen command
        logger.info(f"Executing single-run model: {agent.cmd}")
        try:
            _execute(agent)
        except subprocess.CalledProcessError as e:
            logger.error(f"NGen execution failed with return code {e.returncode}")
            raise

        # Evaluate results and postprocess
        output_iter_path = Path(agent.job.workdir) / "Output_Iteration"
        output_iter_path.mkdir(parents=True, exist_ok=True)

        agent.model.postprocess_single_calibration_output(agent)
        # if isinstance(agent.model, NoCalibModel):
        agent.model.create_validation_configs(agent)
        agent.model.write_run_complete_file(agent.run_name, Path(agent.job.workdir))
        complete_msg(
            agent.model.basinID,
            agent.run_name,
            str(agent.job.workdir),
            agent.model.user,
        )


def dds_set(start_iteration: int, iterations: int, agent: "Agent") -> None:
    """Perform parameter optimization using DDS algorithm.

    parameters
    ----------
    start_iteration : starting iteration
    iterations : total number of iterations
    agent : Agent object

    """
    # from .configuration import NoCalibModel
    from math import log

    from .search import _evaluate, _execute, dds_update
    from .utils import complete_msg

    if iterations < 2:
        raise ValueError("iterations must be >= 2")
    if start_iteration > iterations:
        raise ValueError("start_iteration must be <= iterations")

    neighborhood_size = agent.parameters.get("neighborhood", 0.2)
    calibration_sets = agent.model.adjustables
    init = start_iteration - 1 if start_iteration > 0 else start_iteration
    # Update parameters for all groups before each run
    for calibration_set in calibration_sets:
        evaluatable_objects = _get_evaluatable_objs(calibration_set)
        for calibration_object in evaluatable_objects:
            calibration_object.df["sigma"] = neighborhood_size * (
                calibration_object.df["max"] - calibration_object.df["min"]
            )
            calibration_object.df_fill(init)
            agent.update_config(
                init,
                calibration_object.adf[[str(init), "param", "model"]],
                calibration_object.id,
            )

    # Write realization file to worker directory
    agent.model.strategy.write_realization_file(path=Path(agent.job.workdir))

    if start_iteration == 0:
        if calibration_set.output is None:
            logger.info(f"Running {agent.cmd} to produce initial simulation")
            _execute(agent, start_iteration)
        with pushd(agent.job.workdir):
            _evaluate(
                0, calibration_sets, agent, first_iter_for_agent=True, info=True
            )
        for calibration_set in calibration_sets:
            calibration_set.check_point(agent.job.workdir)
        start_iteration += 1

    for i in range(start_iteration, iterations + 1):
        inclusion_probability = 1 - log(i) / log(iterations)
        for calibration_set in calibration_sets:
            evaluatable_objects = _get_evaluatable_objs(calibration_set)
            # Generate new parameters once per group
            calibration_object = evaluatable_objects[0]
            dds_update(i, inclusion_probability, calibration_object, agent)
            agent.update_config(
                i,
                calibration_object.adf[[str(i), "param", "model"]],
                calibration_object.id
            )

        # Write realization file with all updated parameters
        agent.model.strategy.write_realization_file(path=Path(agent.job.workdir))

        logger.info(f"Running {agent.cmd} for iteration {i}")
        _execute(agent, i)
        with pushd(agent.job.workdir):
            _evaluate(i, calibration_sets, agent, first_iter_for_agent=False)
        for calibration_set in calibration_sets:
            calibration_set.check_point(agent.job.workdir)

    # Create validation files with parameters from all groups
    primary_set = calibration_sets[0]

    # Collect parameters from all groups
    group_adfs = []
    for calibration_set in calibration_sets:
        group_adfs.append(calibration_set.adjustables[0].adf)
    combined_adf = pd.concat(group_adfs, ignore_index=True)

    create_valid_realization_file(
        agent,
        primary_set.eval_params,
        combined_adf,
        "valid_control",
    )
    create_valid_realization_file(
        agent,
        primary_set.eval_params,
        combined_adf,
        "valid_best",
    )
    primary_set.write_run_complete_file(agent.run_name, agent.workdir)
    complete_msg(
        primary_set.basinID,
        agent.run_name,
        agent.workdir,
        primary_set.user,
    )


def compute(
    calibration_sets: List["CalibrationSet"], iteration: int, agent_1st: str, input: Tuple
) -> float:
    """Execute run and evaluate objection function.

    parameters
    ----------
    calibration_sets : List of CalibrationSet objects
    iteration : starting iteration
    agent_1st: name of first agent
    input : Agent and associated parameters

    """
    params = input[0]
    agent = input[1]

    # determine whether it is the first iteration for the agent
    agent_name = (
        os.path.basename(agent.job.workdir).replace("ngen_", "").replace("_worker", "")
    )
    first_iter_for_agent = (
        True if (agent_name != agent_1st) and (iteration == 1) else False
    )

    # Update all groups with new parameters
    idx = 0
    for cal_set in calibration_sets:
        group_dims = len(cal_set.adjustables[0].df)
        param_values = params[idx:idx + group_dims]
        for cal_obj in cal_set.adjustables:
            cal_obj.df[str(iteration)] = param_values

        # Apply updated parameters to realization
        for cal_obj in cal_set.adjustables:
            agent.update_config(
                iteration,
                cal_obj.df[[str(iteration), "param", "model"]],
                cal_obj.id
            )

        # Write realization file with all updated parameters
        agent.model.strategy.write_realization_file(path=Path(agent.job.workdir))

        idx += group_dims

    # Execute run with the updated parameter set and evaluate objective function
    with pushd(agent.job.workdir):
        _execute(agent, iteration)
        cost = _evaluate(iteration, calibration_sets, agent, first_iter_for_agent)
        for cal_set in calibration_sets:
            cal_set.check_point(agent.job.workdir)
    return cost


def cost_func(
    params: pd.DataFrame,
    calibration_sets: List["CalibrationSet"],
    agents: "Agent",
    agent_1st: str,
    pool: int,
):
    """Compute cost function for each iteration.

    Parameters:
    ----------
    calibration_sets : List of CalibrationSet objects
    agents : Agent object
    agent_1st: name of first agent
    pool : Pool size
    params : Parameter set

    Returns:
    ----------

    """
    global __iteration_counter
    # TODO implement multi-processing here???
    func = partial(compute, calibration_sets, __iteration_counter, agent_1st)
    inputs = list(zip(params, agents[:len(params)]))
    costs = np.fromiter(pool.imap(func, inputs), dtype=float)
    __iteration_counter = __iteration_counter + 1

    return costs


def pso_search(start_iteration: int, iterations: int, agent: "Agent") -> None:
    """Search optimal parameter set using PSO algorithm.

    parameters
    ----------
    start_iteration : starting iteration
    iterations : total number of iterations
    agent : Agent object

    """
    import pyswarms as ps

    # Utilizing PSO optimizers requires n "particles" to run -- so we need to take the existing meta
    # and create a unique copy customized for each particle, so then each one gets an execution/update
    num_particles = agent.parameters.get("particles", 4)
    pool_size = agent.parameters.get("pool", 1)
    logger.info(
        "Running PSO with {} particles using {} processes".format(
            num_particles, pool_size
        )
    )

    # name of first agent
    agent_1st = (
        os.path.basename(agent.job.workdir).replace("ngen_", "").replace("_worker", "")
    )

    # TODO warn about potential loss of data when particles > pool
    _pool = pool.Pool(pool_size)
    agents = [agent] + [agent.duplicate() for i in range(num_particles - 1)]
    default_options = {"c1": 0.5, "c2": 0.3, "w": 0.9}
    options = agent.parameters.get("options", default_options)

    calibration_sets = agent.model.adjustables

    # Produce the baseline simulation output for first agent
    if start_iteration == 0:
        if calibration_sets[0].output is None:
            logger.info(
                "Running {} to produce initial simulation".format(agent.cmd)
            )
            for calibration_set in calibration_sets:
                # Only update first catchment in group
                calibration_object = calibration_set.adjustables[0]
                calibration_object.df_fill(start_iteration)
                agent.update_config(
                    start_iteration,
                    calibration_object.adf[[str(start_iteration), "param", "model"]],
                    calibration_object.id,
                )
            # Write realization file with all updated parameters
            agent.model.strategy.write_realization_file(path=Path(agent.job.workdir))
            _execute(agent, start_iteration)
        with pushd(agent.job.workdir):
            _evaluate(
                0, calibration_sets, agent, first_iter_for_agent=True, info=True
            )
        for calibration_set in calibration_sets:
            calibration_set.check_point(agent.job.workdir)

    # Get bounds from all groups
    all_bounds = []
    all_dims = 0
    for calibration_set in calibration_sets:
        bounds = calibration_set.adjustables[0].bounds
        all_bounds.append((bounds[0].values, bounds[1].values))
        all_dims += len(calibration_set.adjustables[0].df)

    # Flatten bounds
    lower_bounds = np.concatenate([b[0] for b in all_bounds])
    upper_bounds = np.concatenate([b[1] for b in all_bounds])
    bounds = (lower_bounds, upper_bounds)

    # Call instance of PSO
    # TODO hook other pyswarm algorithms by user selection
    # TODO hook swarmpackagepy algorithms by user selection (they follow a very similar functional pattern)
    # A quick look at swarmpackagepy shows that it might be a little more challenging since it does this to update states:
    """
        Pbest = self.__agents[
            np.array([function(x) for x in self.__agents]).argmin()]
        if function(Pbest) < function(Gbest):
            Gbest = Pbest
    """
    # meaning that the cost_func is called multiple time PER ITERATION, which doesn't coincide with the architecture
    # we are using here to interface with pyswarm, which only calls the cost_func once per iteration, and tracks other states internally
    # this is a significant problem, especially considering the computation costs of our "cost_function"
    optimizer = ps.single.GlobalBestPSO(
        n_particles=num_particles,
        dimensions=all_dims,
        options=options,
        bounds=bounds,
    )
    cf = partial(cost_func,
                 calibration_sets=calibration_sets,
                 agents=agents,
                 agent_1st=agent_1st,
                 pool=_pool)

    # Perform optimization
    # For pyswarm, DO NOT use the embedded multi-processing -- it is impossible to track the mapping of an agent to the params
    cost, pos = optimizer.optimize(cf, iters=iterations, n_processes=None)

    # Update best position across all groups (only for first cal_obj in each group)
    idx = 0
    for calibration_set in calibration_sets:
        calibration_object = calibration_set.adjustables[0]
        group_dims = len(calibration_object.df)
        calibration_object.df.loc[:, "global_best"] = pos[idx:idx + group_dims]
        logger.info(calibration_object.df[["param", "global_best"]].set_index("param"))
        calibration_object.check_point(agent.workdir)
        idx += group_dims
    logger.info("Best params with cost {}:".format(cost))

    # Get df from each group and stack parameters
    group_dfs = []
    for calibration_set in calibration_sets:
        group_dfs.append(calibration_set.adjustables[0].df)
    combined_df = pd.concat(group_dfs, ignore_index=True)

    # Save and plot history
    cost_hist_file = calibration_sets[0].write_hist_file(
        optimizer, agent, combined_df
    )

    plot_cost_func(calibration_sets[0], agent, cost_hist_file, agent.algorithm)

    # Create configuration files for validation run
    # calibration_object.create_valid_realization_file(agent, calibration_object.df)
    for calibration_set in calibration_sets:
        calibration_object = calibration_set.adjustables[0]
        calibration_object.df[str(iterations)] = calibration_object.df["global_best"]
        calibration_object.df_fill(iterations)
        calibration_object.adf["global_best"] = calibration_object.adf[str(iterations)]

    # Create validation files with parameters from all groups
    primary_set = calibration_sets[0]

    # Get adf from each group and stack parameters
    group_adfs = []
    for calibration_set in calibration_sets:
        if calibration_set.adjustables:
            group_adfs.append(calibration_set.adjustables[0].adf)
    combined_adf = pd.concat(group_adfs, ignore_index=True)

    create_valid_realization_file(
        agent,
        primary_set.eval_params,
        combined_adf,
        "valid_control",
    )
    create_valid_realization_file(
        agent,
        primary_set.eval_params,
        combined_adf,
        "valid_best"
    )

    # Indicate completion
    primary_set.write_run_complete_file(agent.run_name, agent.workdir)
    complete_msg(
        primary_set.basinID,
        agent.run_name,
        agent.workdir,
        primary_set.user,
    )


def gwo_search(start_iteration: int, iterations: int, agent) -> None:
    """Search optimal parameter set using GWO algorithm.

    parameters
    ----------
    start_iteration : start iteration
    iterations : total number of iterations
    agent : Agent object

    """
    global __iteration_counter
    __iteration_counter = (
        start_iteration + 1 if start_iteration == 0 else start_iteration
    )
    logger.info(f"_iteration_counter is {__iteration_counter}")
    num_particles = agent.parameters.get("particles", 10)
    pool_size = agent.parameters.get("pool", num_particles)
    logger.info(
        "Running GWO with {} particles using {} processes".format(
            num_particles, pool_size
        )
    )
    _pool = pool.Pool(pool_size)

    # name of first agent
    agent_1st = (
        os.path.basename(agent.job.workdir).replace("ngen_", "").replace("_worker", "")
    )

    if start_iteration == 0:
        agents = [agent] + [agent.duplicate() for i in range(num_particles - 1)]
    else:
        agents = [agent] + [
            agent.duplicate(restart_flag=True, agent_counter=i + 1)
            for i in range(num_particles - 1)
        ]
        for agent in agents:
            if len(glob.glob(os.path.join(agent.job.workdir, "*.log"))) != 1:
                agent.restart()

    calibration_sets = agent.model.adjustables

    # Produce the baseline simulation output for first agent
    if start_iteration == 0:
        if calibration_sets[0].output is None:
            logger.info(
                "Running {} to produce initial simulation".format(agent.cmd)
            )
            # agent.update_config(start_iteration, calibration_object.df[[str(start_iteration), 'param', 'model']], calibration_object.id)
            for calibration_set in calibration_sets:
                calibration_object = calibration_set.adjustables[0]
                calibration_object.df_fill(start_iteration)
                agent.update_config(
                    start_iteration,
                    calibration_object.adf[[str(start_iteration), "param", "model"]],
                    calibration_object.id,
                )
            # Write realization file with all updated parameters
            agent.model.strategy.write_realization_file(path=Path(agent.job.workdir))
            _execute(agent, start_iteration)

        with pushd(agent.job.workdir):
            logger.info("Evaulating iteration 0")
            _evaluate(
                0, calibration_sets, agent, first_iter_for_agent=True, info=True
            )
            logger.info("Finished evaluating iteration 0")

        for calibration_set in calibration_sets:
            calibration_set.check_point(agent.job.workdir)

    # Get bounds from all groups
    all_bounds = []
    all_dims = 0
    for calibration_set in calibration_sets:
        bounds = calibration_set.adjustables[0].bounds
        all_bounds.append((bounds[0].values, bounds[1].values))
        all_dims += len(calibration_set.adjustables[0].df)

    # Flatten bounds
    lower_bounds = np.concatenate([b[0] for b in all_bounds])
    upper_bounds = np.concatenate([b[1] for b in all_bounds])
    bounds = (lower_bounds, upper_bounds)

    # Initialize swarms
    optimizer = GlobalBestGWO(
        n_particles=num_particles,
        dimensions=all_dims,
        bounds=bounds,
        start_iter=start_iteration,
        calib_path=agent.calib_path,
        basinid=calibration_sets[0].basinID,
    )
    cf = partial(cost_func, calibration_sets=calibration_sets, agents=agents, agent_1st=agent_1st, pool=_pool)

    if iterations < 1:
        msg = "iterations must be >= 1 for GWO."
        logger.error(msg)
        raise ValueError(msg)

    # Perform optimization with one fewer iterations than requested since GlobalBestGWO.optimize()
    # (in gwo_global_best.py) does an extra iteration during its initialization
    cost, pos = optimizer.optimize(cf, iters=iterations - 1, n_processes=None)

    # Update global best across all groups
    idx = 0
    for calibration_set in calibration_sets:
        calibration_object = calibration_set.adjustables[0]
        group_dims = len(calibration_object.df)
        calibration_object.df.loc[:, "global_best"] = pos[idx:idx + group_dims]
        calibration_object.check_point(agent.workdir)
        idx += group_dims
    logger.info("Best params with cost {}:".format(cost))

    # Save and plot history
    group_dfs = []
    for calibration_set in calibration_sets:
        group_dfs.append(calibration_set.adjustables[0].df)
    combined_df = pd.concat(group_dfs, ignore_index=True)

    cost_hist_file = calibration_sets[0].write_hist_file(
        optimizer, agent, combined_df
    )
    plot_cost_func(calibration_sets[0], agent, cost_hist_file, agent.algorithm)

    # Create configuration files for validation run
    for calibration_set in calibration_sets:
        calibration_object = calibration_set.adjustables[0]
        calibration_object.df[str(iterations)] = calibration_object.df["global_best"]
        calibration_object.df_fill(iterations)
        calibration_object.adf["global_best"] = calibration_object.adf[str(iterations)]

    # Create validation files with parameters from all groups
    primary_set = calibration_sets[0]

    # Get adf from each group and stack parameters
    group_adfs = []
    for calibration_set in calibration_sets:
        if calibration_set.adjustables:
            group_adfs.append(calibration_set.adjustables[0].adf)
    combined_adf = pd.concat(group_adfs, ignore_index=True)

    create_valid_realization_file(
        agent,
        primary_set.eval_params,
        combined_adf,
        "valid_control",
    )
    create_valid_realization_file(
        agent,
        primary_set.eval_params,
        combined_adf,
        "valid_best"
    )

    # Indicate completion
    primary_set.write_run_complete_file(agent.run_name, agent.workdir)
    complete_msg(
        primary_set.basinID,
        agent.run_name,
        agent.workdir,
        primary_set.user,
    )
