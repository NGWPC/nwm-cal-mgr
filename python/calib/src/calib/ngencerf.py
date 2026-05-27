import requests
import time
from common import ensure_logger_initialized
from urllib.parse import urljoin, urlparse


class ReportIterationError(RuntimeError):
    pass


def _logger():
    return ensure_logger_initialized()


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
NGENCERF_REPORT_ITERATION_ENDPOINT = "calibration/report_iteration/"

# Retry configuration (same semantics as the Bash script)
RETRY_DELAY = 300  # seconds between retries (5 minutes)
MAX_RETRIES = 144  # 12 hours total retry window


def normalize_url(url: str) -> str:
    """
    Normalize a base URL by adding a default http:// scheme if one is not provided.

    Examples:
        localhost:8000        -> http://localhost:8000
        myserver.com          -> http://myserver.com
        http://foo.com        -> http://foo.com
        https://foo.com       -> https://foo.com
    """
    url = url.strip()

    parsed = urlparse(url)

    if not parsed.scheme:
        url = f"http://{url}"

    return url


def validate_url(url: str, name: str) -> None:
    """
    Validate that a normalized URL contains an HTTP/HTTPS scheme and network location.

    Examples of valid normalized values:
        http://localhost:8000
        https://myserver.com
        https://myserver.com/api/

    Examples of invalid normalized values:
        ""
        http:///api/foo
        ftp://myserver.com
    """
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ReportIterationError(
            f"Invalid {name}: unsupported URL scheme: '{url}'. "
            f"Expected http:// or https://"
        )

    if not parsed.netloc:
        raise ReportIterationError(
            f"Invalid {name}: missing hostname: '{url}'"
        )


def report(
        calibration_run_id: int,
        iteration: int,
        worker: str,
        first_iteration: bool,
        auth_token: str,
        ngencerf_base_url: str
) -> None:
    """
    Report a calibration iteration result to the ngenCerf server.

    This function is resilient to temporary network failures:
      - Retries every 5 minutes, up to 12 hours, if the server is unreachable.
      - Does not retry HTTP responses such as 400, 404, or 500, because those
        mean the server received the request and returned an application-level
        or server-side error.
      - Raises a fatal exception if the report cannot be posted successfully.
    """

    # Normalize and validate the base URL before constructing the API endpoint URL
    ngencerf_base_url = normalize_url(ngencerf_base_url)
    validate_url(ngencerf_base_url, "ngencerf_base_url")

    url = urljoin(
        ngencerf_base_url,
        NGENCERF_REPORT_ITERATION_ENDPOINT
    )

    # Prepare request payload and headers
    payload = {
        "calibration_run_id": calibration_run_id,
        "iteration": iteration,
        "worker_name": worker,
        "first_iteration_for_worker": first_iteration,
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {auth_token}",
    }

    _logger().info(f"Reporting iteration to ngenCerf server - url={url}, payload={payload}")

    # ─────────────────────────────────────────────────────────────
    # Retry loop:
    # - Only retries connection-level errors, such as server down, DNS failure,
    #   refused connection, or request timeout.
    # - Does NOT retry HTTP responses, such as 400, 404, or 500, because those
    #   mean the server responded. Retrying the same invalid request is unlikely
    #   to fix the problem and could hide the real failure.
    # - Raises a fatal exception if the iteration report is not accepted.
    # ─────────────────────────────────────────────────────────────
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _logger().info(f"Reporting iteration to {url} - payload: {payload}")

            # Send POST request with a timeout to prevent hanging indefinitely
            response = requests.post(url, json=payload, headers=headers, timeout=30)

            # If we get here, the server responded. Check for HTTP errors.
            response.raise_for_status()

            # If successful, parse and log the response message
            try:
                response_json = response.json()
            except ValueError as e:
                raise ReportIterationError(
                    f"Invalid JSON response from ngenCerf server: url={url}, "
                    f"status_code={response.status_code}, response={response.text}"
                ) from e

            message = response_json.get("message")
            _logger().info(f"Response from report_iteration: {message}")
            return  # Done, no need to retry

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            # Server is unreachable or did not respond within the timeout
            _logger().warning(f"Server unreachable on attempt {attempt}/{MAX_RETRIES}: {e}")

            # Stop after MAX_RETRIES to avoid endless looping
            if attempt >= MAX_RETRIES:
                raise ReportIterationError(
                    f"Failed to report iteration after {MAX_RETRIES} attempts: "
                    f"url={url}, payload={payload}"
                ) from e

            # Wait before retrying
            _logger().info(f"Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)

        except requests.exceptions.HTTPError as e:
            http_response = e.response
            status_code = http_response.status_code if http_response is not None else "<unknown>"
            response_text = http_response.text if http_response is not None else "<no response body>"

            # Server responded with an HTTP error. Do not retry.
            raise ReportIterationError(
                f"Call to ngenCerf server failed: "
                f"url={url}, status_code={status_code}, response={response_text}"
            ) from e

        except Exception as e:
            raise ReportIterationError(
                f"Unexpected error while reporting iteration: url={url}, payload={payload}"
            ) from e
