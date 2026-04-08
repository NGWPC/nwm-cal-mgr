"""
This is main script to execute validation control run using the default model
parameter set and validation best run using the best calibrated parameter set.

@author: Xia Feng
"""
import sys
import argparse
import os
from pathlib import Path
from pprint import pprint

import yaml
from calib.agent import Agent
from calib.configuration import General
from calib.utils import set_os_env_key, OS_ENV_KEY_RESULTS_DIR
from calib.validation_run import run_valid_ctrl_best

from common import (
    str_to_bool,
    ensure_logger_initialized,
    initialize_logger,
    build_validation_log_file_name,
)


def _logger():
    return ensure_logger_initialized()


def main(general: General, model_conf):
    # Seed the random number generators if requested
    if general.random_seed is not None:
        import random

        random.seed(general.random_seed)
        import numpy as np

        np.random.seed(general.random_seed)

    # Initialize agent
    agent = Agent(model_conf, general.valid_path, general, general.log, general.restart)

    # set environment variable for ngencerf backend
    print(f"ngen env var {OS_ENV_KEY_RESULTS_DIR} set to {agent.job.workdir}",flush=True)
    set_os_env_key(
        OS_ENV_KEY_RESULTS_DIR, str(Path(agent.job.workdir)), override=False
    )

    # read nwm retrospective streamflow if exists
    if agent.run_name != "valid_control":
        if "nwmflow" not in model_conf.keys() or model_conf["nwmflow"] is None:
            agent.nwmflow_file = ""
            _logger().info("No NWM retrospective streamflow simulation is available for this location")
        else:
            agent.nwmflow_file = model_conf["nwmflow"]

    # Execute validation control and best simulation
    run_valid_ctrl_best(agent)

    _logger().info("Validation completed")



def cli():
    """Command-line interface entry point for nwm-validation."""
    parser = argparse.ArgumentParser(description="Run Validation in NGEN architecture.")
    parser.add_argument(
        "config_file",
        nargs="?",
        default=None,
        type=Path,
        help="The configuration yaml file for catchments to be operated on",
    )
    parser.add_argument(
        "--log_path_overwrite",
        required=False,
        type=str,
        help="""
        If provided, this file path will be used for logging. If a filename, the file will be overwritten.
        If not provided, a log file path will be decided by the program."""
    )
    parser.add_argument(
        "--logging_enabled",
        required=False,
        type=str_to_bool,
        help="""
        Enable or disable cal-mgr logging.
        Accepts: true/false, yes/no, on/off, 1/0."""
    )
    parser.add_argument(
        "--log_file_name",
        required=False,
        type=str,
        help="""
        If provided, this file name will be used for cal-mgr logging, otherwise it will be decided by the program."""
    )
    parser.add_argument(
        "--log_level",
        required=False,
        type=str,
        help="""
        If provided, this log level will be used for cal-mgr logging. (default=INFO)."""
    )

    args = parser.parse_args()

    if args.config_file is None:
        print("validation.py: no config_file provided; skipping validation.")
        return

    with open(args.config_file) as file:
        conf = yaml.safe_load(file)

    general_conf = conf["general"]

    run_kind = general_conf["name"]
    workdir = Path(general_conf["workdir"])
    default_log_dir = workdir / run_kind / "logs"
    calibration_run_id = general_conf.get("calibration_run_id")

    default_log_file_name = build_validation_log_file_name(
        calibration_run_id=calibration_run_id,
        worker_name=None,
        run_kind=run_kind,
    )

    global LOG
    LOG = initialize_logger(
        log_path_overwrite=args.log_path_overwrite,
        log_file_name_override=args.log_file_name or default_log_file_name,
        log_level_override=args.log_level,
        enabled_override=args.logging_enabled,
        reset_file=True,
        default_log_dir=default_log_dir,
    )

    # This is no longer necessary since it is part of the GUI now. Keeping the call,
    # but commented out, in case we ever want to include it again.
    # Add to top: from calib.git_util import print_git_info_all
    # print_git_info_all()

    general = General(**conf["general"])

    os.chdir(general.workdir)

    main(general, conf["model"])


if __name__ == "__main__":
    cli()
