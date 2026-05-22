#!/bin/bash

LOG_PREFIX="[run-nwm-cal-mgr.sh]"

# This shell script lives in the nwm-cal-mgr repo.
# It is used by CerfServer runtime containers to invoke nwm-cal-mgr scripts.

VALID_COMMANDS=("calibration" "validation" "validation_iteration")

CALIB_SCRIPT=/ngen-app/nwm-cal-mgr/python/calibration.py
VALID_SCRIPT=/ngen-app/nwm-cal-mgr/python/validation.py
VALID_ITERATION_SCRIPT=/ngen-app/nwm-cal-mgr/python/validation_iteration.py

# Set the umask so files and directories are created with 777 permissions
umask 000

show_help() {
  echo "Usage: $(basename "$0") <command> <input_file> [worker_name iteration_number] [stdout_file]"
  echo ""
  echo "COMMAND:"
  echo "  calibration          Run calibration script."
  echo "  validation           Run validation script."
  echo "  validation_iteration Run validation iteration script; requires worker_name and iteration_number."
  echo ""
  echo "INPUT_FILE: Path to the input file required by the script."
  echo "WORKER_NAME: Required for validation_iteration."
  echo "ITERATION_NUMBER: Required for validation_iteration."
  echo "STDOUT_FILE: Optional path where script console output will be saved."
  echo ""
  echo "Examples:"
  echo "  $(basename "$0") calibration /path/to/input.csv"
  echo "  $(basename "$0") validation /path/to/input.csv /path/to/output.log"
  echo "  $(basename "$0") validation_iteration /path/to/input.csv worker1 5 /path/to/output.log"
  echo ""
  exit 1
}

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  show_help
fi

if [ -z "$1" ]; then
  echo "$LOG_PREFIX Error: No script command provided. Allowable commands are: ${VALID_COMMANDS[*]}."
  show_help
fi

SCRIPT_COMMAND=$1
shift 1

case "$SCRIPT_COMMAND" in
  "calibration")
    SCRIPT_PATH=$CALIB_SCRIPT
    REQUIRED_ARGS=1
    ;;
  "validation")
    SCRIPT_PATH=$VALID_SCRIPT
    REQUIRED_ARGS=1
    ;;
  "validation_iteration")
    SCRIPT_PATH=$VALID_ITERATION_SCRIPT
    REQUIRED_ARGS=3
    ;;
  *)
    echo "$LOG_PREFIX Error: Invalid script command: '$SCRIPT_COMMAND'. Allowable commands are: ${VALID_COMMANDS[*]}."
    show_help
    ;;
esac

if [ ! -f "$SCRIPT_PATH" ]; then
  echo "$LOG_PREFIX Error: Script not found at $SCRIPT_PATH"
  exit 1
fi

# Check if the correct number of arguments are provided for the selected command
if [ $# -lt "$REQUIRED_ARGS" ]; then
  echo "$LOG_PREFIX Error: Insufficient arguments. $SCRIPT_COMMAND requires $REQUIRED_ARGS arguments."
  show_help
fi

# Get the input file and additional parameters for validation_iteration
INPUT_FILE=$1
shift 1

echo "$LOG_PREFIX Input file: $INPUT_FILE"

if [ "$SCRIPT_COMMAND" == "validation_iteration" ]; then
  WORKER_NAME=$1
  ITERATION_NUMBER=$2
  shift 2

  echo "$LOG_PREFIX Worker name: $WORKER_NAME"
  echo "$LOG_PREFIX Iteration number: $ITERATION_NUMBER"
fi

STDOUT_FILE=""
if [ $# -ge 1 ]; then
  STDOUT_FILE=$1
  shift 1

  echo "$LOG_PREFIX Output file: $STDOUT_FILE"

  STDOUT_DIR=$(dirname "$STDOUT_FILE")
  mkdir --parents "$STDOUT_DIR"
fi

if [ $# -gt 0 ]; then
  echo "$LOG_PREFIX Error: Unexpected extra arguments: $*"
  show_help
fi

echo "$LOG_PREFIX Running $(basename "$SCRIPT_PATH") with input file: $INPUT_FILE"

if [ "$SCRIPT_COMMAND" == "validation_iteration" ]; then
  if [ -z "$STDOUT_FILE" ]; then
    python "$SCRIPT_PATH" "$INPUT_FILE" "$WORKER_NAME" "$ITERATION_NUMBER"
  else
    python "$SCRIPT_PATH" "$INPUT_FILE" "$WORKER_NAME" "$ITERATION_NUMBER" > "$STDOUT_FILE" 2>&1
  fi
else
  if [ -z "$STDOUT_FILE" ]; then
    python "$SCRIPT_PATH" "$INPUT_FILE"
  else
    python "$SCRIPT_PATH" "$INPUT_FILE" > "$STDOUT_FILE" 2>&1
  fi
fi

python_exit_code=$?

if [ $python_exit_code -ne 0 ]; then
  echo "$LOG_PREFIX $(basename "$SCRIPT_PATH") exited with code $python_exit_code"
fi

if [ -n "$STDOUT_FILE" ]; then
  echo "$LOG_PREFIX Output from running $(basename "$SCRIPT_PATH")"
  echo "-------------- start of $STDOUT_FILE -----------------------------"
  cat "$STDOUT_FILE"
  echo "---------------- end of $STDOUT_FILE -----------------------------"
fi

echo "$LOG_PREFIX Done running $(basename "$SCRIPT_PATH")"

exit $python_exit_code
