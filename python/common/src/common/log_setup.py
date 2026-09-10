from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import inspect
import argparse
import logging
import re

try:
    import ewts
    from ewts.modules import CAL_MGR_ID
    EWTS_AVAILABLE = True
except ImportError:
    EWTS_AVAILABLE = False
    CAL_MGR_ID = "CALMGR"


def str_to_bool(value: str) -> bool:
    value = value.lower()
    if value in {"true", "t", "yes", "y", "1", "on", "enabled", "enable"}:
        return True
    if value in {"false", "f", "no", "n", "0", "off", "disabled", "disable"}:
        return False
    raise argparse.ArgumentTypeError(
        f"Invalid boolean value: '{value}'"
    )


def create_timestamp(
    fmt: Literal["default", "compact"] = "default"
) -> str:
    now = datetime.now(timezone.utc)

    if fmt == "compact":
        return now.strftime("%Y%m%dT%H%M%S")

    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def build_calibration_log_file_name(
    *,
    calibration_run_id: int | None,
    bootstrap: bool = False
) -> str:
    job_id = calibration_run_id
    if calibration_run_id:
        base =  f"cal_mgr_job_{calibration_run_id}_calib"
    else:
        base  =  f"cal_mgr_{create_timestamp('compact')}_calib"

    if bootstrap:
        return f"{base}_bootstrap.log"
    
    return f"{base}.log"

def build_validation_log_file_name(
    *,
    calibration_run_id: int | None,
    worker_name: str | None = None,
    run_kind: str,
    algorithm: str,
    iteration: int | None = None,
    bootstrap: bool = False
) -> str:
    """
    run_kind:
      - valid_control
      - valid_best
      - iter
    """
    if calibration_run_id:
        prefix = f"cal_mgr_job_{calibration_run_id}"
    else:
        prefix = f"cal_mgr_{create_timestamp('compact')}"

    if run_kind not in {"valid_control", "valid_best", "iter"}:
        raise ValueError(f"Unsupported run_kind: {run_kind}")
    elif run_kind == "iter": 
        run_kind_suffix = f"_{worker_name}" if not bootstrap else f"_valid_{worker_name}_iter{iteration}"
    else:   
        run_kind_suffix = f"_{run_kind}"

    if bootstrap:
        return f"{prefix}{run_kind_suffix}_bootstrap.log"
    
    return f"{prefix}{run_kind_suffix}.log"


def resolve_log_target(
    *,
    log_path_overwrite: str | None = None,
    log_file_name_override: str | None = None,
    default_log_dir: str | Path | None = None,
) -> tuple[Path, str]:
    resolved_log_dir: Path | None = None
    resolved_log_file_name: str | None = None

    if log_path_overwrite:
        log_path = Path(log_path_overwrite)
        print(f"log_path_overwrite = {log_path!s}")

        if log_path.exists():
            if log_path.is_dir():
                resolved_log_dir = log_path
                resolved_log_file_name = log_file_name_override or "cal_mgr.log"
            else:
                resolved_log_dir = log_path.parent
                resolved_log_file_name = log_path.name
        else:
            if str(log_path_overwrite).endswith(("/", "\\")):
                resolved_log_dir = log_path
                resolved_log_file_name = log_file_name_override or "cal_mgr.log"
            elif log_path.suffix:
                resolved_log_dir = log_path.parent
                resolved_log_file_name = log_path.name
            else:
                resolved_log_dir = log_path
                resolved_log_file_name = log_file_name_override or "cal_mgr.log"
    else:
        if default_log_dir is not None:
            resolved_log_dir = Path(default_log_dir)
            resolved_log_file_name = (
                log_file_name_override or f"cal_mgr_{create_timestamp('compact')}.log"
            )
        else:  # if default_log_dir is None, send logs to stdout only, do not create log file
            resolved_log_dir = None
            resolved_log_file_name = None

    return resolved_log_dir, resolved_log_file_name


def _attach_file_handler(logger: logging.Logger, full_log_path: Path, log_level: str) -> None:
    """Add/replace a FileHandler on an already-configured logger without touching
    its existing handlers (e.g. the stdout StreamHandler set up before this call)."""
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
            handler.close()

    file_handler = logging.FileHandler(full_log_path)
    file_handler.setLevel(log_level)
    for handler in logger.handlers:
        if handler.formatter is not None:
            file_handler.setFormatter(handler.formatter)
            break
    logger.addHandler(file_handler)


def _remove_console_handlers(logger: logging.Logger) -> None:
    """Remove handlers that write to a stream (e.g. stdout/stderr) but are not
    file handlers. FileHandler is itself a StreamHandler subclass, so this
    excludes FileHandler instances explicitly rather than relying on isinstance."""
    for handler in list(logger.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)


def initialize_logger(
    *,
    log_path_overwrite: str | None = None,
    log_level_override: str | None = None,
    log_file_name_override: str | None = None,
    enabled_override: bool | None = None,
    reset_file: bool = False,
    default_log_dir: str | Path | None = None,
) -> ewts.logger.EwtsLogger | logging.Logger:
    log_level = log_level_override if log_level_override is not None else "INFO"

    if not EWTS_AVAILABLE and not log_path_overwrite:
        # No explicit log_path_overwrite and EWTS unavailable: keep using the
        # already-configured stdout logger as-is, no default log file.
        print("CALMGR stdout logging only (no log_path_overwrite, EWTS unavailable)", flush=True)
        logger = logging.getLogger(CAL_MGR_ID)
        logger.setLevel(log_level)
        logger.disabled = enabled_override is False
        return logger

    resolved_log_dir, resolved_log_file_name = resolve_log_target(
        log_path_overwrite=log_path_overwrite,
        log_file_name_override=log_file_name_override,
        default_log_dir=default_log_dir,
    )

    if resolved_log_dir is not None:
        resolved_log_dir.mkdir(parents=True, exist_ok=True)
        full_log_path = resolved_log_dir / resolved_log_file_name

    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    full_log_path = resolved_log_dir / resolved_log_file_name

    if reset_file or log_path_overwrite:
        print(
            f"log setup: Deleting file, if already exists, to start a new log file: {full_log_path!s}, ", flush=True
        )
        try:
            full_log_path.unlink()
        except FileNotFoundError:
            pass

    if EWTS_AVAILABLE:
        print(f"CALMGR EWTS Logging into: {full_log_path}", flush=True)
        return ewts.logger.setup_logger(
            CAL_MGR_ID,
            level=log_level,
            log_dir=resolved_log_dir,
            log_file_name=resolved_log_file_name,
            running_in_ngen=False,
            enabled=enabled_override,
        )

    print(f"CALMGR file-only logging into: {full_log_path}", flush=True)
    logger = logging.getLogger(CAL_MGR_ID)
    logger.setLevel(log_level)
    logger.disabled = enabled_override is False
    _attach_file_handler(logger, full_log_path, log_level)
    _remove_console_handlers(logger)
    return logger


def get_calmgr_logger() -> ewts.logger.EwtsLogger | logging.Logger:
    if EWTS_AVAILABLE:
        return ewts.logger.get_logger(CAL_MGR_ID)
    return logging.getLogger(CAL_MGR_ID)
