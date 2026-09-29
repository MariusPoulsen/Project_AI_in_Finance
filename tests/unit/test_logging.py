import io
import json

from structural_break.common.logging import configure_logging, new_run_id


def test_json_log_redacts_credentials_and_omits_exception_payload():
    output = io.StringIO()
    logger = configure_logging(output, secrets=("secret-value",))
    run_id = new_run_id()
    try:
        raise RuntimeError("sensitive request body")
    except RuntimeError:
        logger.exception(
            "Failed secret-value token=abc", extra={"run_id": run_id, "status": "FAILED"}
        )
    payload = json.loads(output.getvalue())
    assert payload["run_id"] == run_id
    assert payload["error_type"] == "RuntimeError"
    assert payload["status"] == "FAILED"
    assert "secret-value" not in output.getvalue()
    assert "abc" not in output.getvalue()
    assert "sensitive request body" not in output.getvalue()
    assert new_run_id() != run_id
