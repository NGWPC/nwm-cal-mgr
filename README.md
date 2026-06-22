# NGen Calibration

**Description**:  Supporting code/workflows for automated calibration of [NGen](https://github.com/noaa-owp/ngen) Formulations using Dynamic Dimensioned Search (DDS), Grey Wolf Optimizer(GWO), and Particle Swarm Optimizer (PSO)


## Repository Structure

```text
nwm-cal-mgr/
├── python/calib/           # Core calibration library
├── python/config/          # Configuration workflow package
├── python/common/          # Common utilities and shared code (e.g., logging)
└── configs/                # Sample configuration files for calibration runs
```

## Dependencies

See [calib/requirements.txt](python/calib/requirements.txt) and [config/requirements.txt](python/config/requirements.txt) for specific python dependencies.

External dependencies include:
- [nwm-msw-mgr](https://github.com/NGWPC/nwm-msw-mgr)
- [nwm_metrics](https://github.com/NGWPC/nwm-eval-mgr/nwm_metrics)
- [ewts](https://github.com/NGWPC/nwm-ewts/runtime/python/ewts)

## Installation

`TODO` [INSTALL](INSTALL.md) document.

## Configuration

You can manually configure a calibration run as shown in the sample config file `configs/config_calib.yaml`. However, 
it is strongly recommended to use the Model Setup Workflow Manager (MSWM) to produce the calibration config file and 
the necessary input files.

Refer to one of the sample input config files in [MSWM](https://github.com/NGWPC/nwm-msw-mgr/tree/development/src/mswm/example_inputs) to set up your configuration for calibration/validation.

## Usage

After installation, the scripts can be executed in two ways:
- As CLI commands: `calibration`, `validation`, `validation_iteration`
- Directly with Python: `python [NWM_ROOT]/nwm-cal-mgr/python/[script].py`

### run MSWM

Run model setup workflow manager (nwm-msw-mgr) to produce input files for calibration/validation.

```bash
python -m mswm.manager build_calib input.config
```
### run calibration

```bash
calibration [CALIB_CONFIG]
# or: python [NWM_ROOT]/nwm-cal-mgr/python/calibration.py [CALIB_CONFIG]
```
Where [CALIB_CONFIG] is the config file for calibration, which can be found in the log file from running MSWM.

### run validation

```bash
validation [VALID_CONTROL_CONFIG]
validation [VALID_BEST_CONFIG]
# or: python [NWM_ROOT]/nwm-cal-mgr/python/validation.py [CONFIG]
```
[VALID_CONTROL_CONFIG] and [VALID_BEST_CONFIG] are the config files for validation runs with the control/default
parameters and the best parameters, respectively. These config files are produced at the end of calibration progress 
(see the log file for paths to these files).

### run validation for an alternative iteration
Optionally, you can run validation for an alternative iteration (i.e., not the control/default or the best) by providing 
the iteration number as an argument. This is useful when you want to check the performance of parameters from a specific 
iteration during the calibration process.

```bash
validation_iteration [CALIB_CONFIG] [worker ID] [iteration number]
# or: python [NWM_ROOT]/nwm-cal-mgr/python/validation_iteration.py [CALIB_CONFIG] [worker ID] [iteration number]
```
Where [worker ID] refers to the middle part of the folder name for a specific calibration run. For example, if the 
calibration run folder is named `ngen_ulu2wno6_worker`, then the worker ID is `ulu2wno6`.

Example:
```bash
# run validation for iteration 5 of the calibration run with worker ID "ulu2wno6"
validation_iteration [CALIB_CONFIG] ulu2wno6 5
```

## How to test the software

`TODO`

## Known issues

## Getting help

If you have questions, concerns, bug reports, etc, please file an issue in this repository's Issue Tracker.

## Getting involved

See [CONTRIBUTING](CONTRIBUTING.md), or open an issue to start a conversation!
----

## Open source licensing info
1. [TERMS](TERMS.md)
2. [LICENSE](LICENSE)


----
