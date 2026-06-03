"""
test_params.py — Tests for parameterized commands with slot-filling.

Covers:
    - Template placeholder detection and extraction
    - Argument validation (reject shell metacharacters)
    - Template substitution
    - Store operations with templates
    - Extraction of args from LLM output
    - Orchestrator wiring with parameterized commands
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure tests/ is on sys.path
_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from src.lever_runner.store import (
    get_placeholders,
    has_placeholders,
    strip_placeholders,
    substitute_args,
    validate_arg,
)
from src.lever_runner.intent_extractor import Extraction, _normalize, _parse_args


# ---------------------------------------------------------------------------
# Placeholder detection
# ---------------------------------------------------------------------------


class TestHasPlaceholders:
    def test_simple_placeholder(self):
        assert has_placeholders("show logs for {{container}}") is True

    def test_multiple_placeholders(self):
        assert has_placeholders("copy {{src}} to {{dst}}") is True

    def test_no_placeholders(self):
        assert has_placeholders("show disk usage") is False

    def test_empty_string(self):
        assert has_placeholders("") is False

    def test_partial_braces(self):
        assert has_placeholders("show {container}") is False

    def test_command_with_placeholder(self):
        assert has_placeholders("docker logs --tail 100 {{container}}") is True


class TestGetPlaceholders:
    def test_single_placeholder(self):
        assert get_placeholders("show logs for {{container}}") == ["container"]

    def test_multiple_unique(self):
        assert get_placeholders("copy {{src}} to {{dst}}") == ["src", "dst"]

    def test_duplicate_placeholder(self):
        # Same placeholder used twice in command
        result = get_placeholders("ping {{host}} and traceroute {{host}}")
        assert result == ["host"]  # deduplicated

    def test_no_placeholders(self):
        assert get_placeholders("show disk usage") == []

    def test_order_preserved(self):
        result = get_placeholders("{{service}} on port {{port}} in {{namespace}}")
        assert result == ["service", "port", "namespace"]


class TestStripPlaceholders:
    def test_strip_single(self):
        assert strip_placeholders("show logs for {{container}}") == "show logs for"

    def test_strip_multiple(self):
        # strip_placeholders removes {{}} but leaves surrounding spaces,
        # then .strip() cleans the edges. Middle spaces remain.
        result = strip_placeholders("restart {{service}} on {{host}}")
        assert "restart" in result and "on" in result and "{{" not in result

    def test_no_placeholders(self):
        assert strip_placeholders("show disk usage") == "show disk usage"

    def test_only_placeholder(self):
        result = strip_placeholders("{{container}}")
        assert result == ""


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


class TestValidateArg:
    def test_alphanumeric(self):
        assert validate_arg("container", "nginx") == "nginx"

    def test_with_dashes(self):
        assert validate_arg("container", "my-container") == "my-container"

    def test_with_underscores(self):
        assert validate_arg("service", "my_service") == "my_service"

    def test_with_dots(self):
        assert validate_arg("file", "config.yaml") == "config.yaml"

    def test_with_numbers(self):
        assert validate_arg("port", "8080") == "8080"

    def test_complex_name(self):
        # Dots, dashes, underscores, alphanumerics are all OK
        assert validate_arg("image", "my-image.v2") == "my-image.v2"

    def test_reject_semicolon(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            validate_arg("cmd", "nginx; rm -rf /")

    def test_reject_pipe(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            validate_arg("cmd", "nginx | cat /etc/passwd")

    def test_reject_backticks(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            validate_arg("cmd", "`rm -rf /`")

    def test_reject_dollar_sign(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            validate_arg("cmd", "$(whoami)")

    def test_reject_ampersand(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            validate_arg("cmd", "nginx && echo pwned")

    def test_reject_spaces(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            validate_arg("cmd", "nginx status")

    def test_reject_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_arg("container", "")

    def test_reject_redirect(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            validate_arg("file", "> /etc/passwd")


# ---------------------------------------------------------------------------
# Template substitution
# ---------------------------------------------------------------------------


class TestSubstituteArgs:
    def test_single_arg(self):
        result = substitute_args("docker logs {{container}}", {"container": "nginx"})
        assert result == "docker logs nginx"

    def test_multiple_args(self):
        result = substitute_args(
            "systemctl restart {{service}}",
            {"service": "sshd"},
        )
        assert result == "systemctl restart sshd"

    def test_arg_in_middle(self):
        result = substitute_args(
            "docker logs --tail 100 {{container}}",
            {"container": "redis"},
        )
        assert result == "docker logs --tail 100 redis"

    def test_missing_arg_raises(self):
        with pytest.raises(ValueError, match="missing arguments: container"):
            substitute_args("docker logs {{container}}", {})

    def test_invalid_arg_raises(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            substitute_args("docker logs {{container}}", {"container": "nx; rm -rf /"})

    def test_no_placeholders_no_args(self):
        result = substitute_args("df -h", {})
        assert result == "df -h"

    def test_extra_args_ignored(self):
        # Extra args in the dict that aren't in the template are fine
        result = substitute_args("docker logs {{container}}", {"container": "nginx", "extra": "val"})
        assert result == "docker logs nginx"


# ---------------------------------------------------------------------------
# Arg parsing from LLM output
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_single_arg(self):
        assert _parse_args("container=nginx") == {"container": "nginx"}

    def test_multiple_args(self):
        result = _parse_args("src=file.txt\ndst=server:/tmp/")
        assert result == {"src": "file.txt", "dst": "server:/tmp/"}

    def test_empty_input(self):
        assert _parse_args("") == {}

    def test_no_equals(self):
        assert _parse_args("no args here") == {}

    def test_with_spaces(self):
        assert _parse_args("  container = nginx  ") == {"container": "nginx"}

    def test_invalid_key_rejected(self):
        # Keys with spaces aren't valid identifiers
        assert _parse_args("my key=value") == {}

    def test_empty_value_rejected(self):
        assert _parse_args("container=") == {}


# ---------------------------------------------------------------------------
# _normalize returns phrase + args
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_phrase_only(self):
        phrase, args = _normalize("show disk usage")
        assert phrase == "show disk usage"
        assert args == {}

    def test_phrase_with_args(self):
        phrase, args = _normalize("show logs for container\ncontainer=nginx")
        assert phrase == "show logs for container"
        assert args == {"container": "nginx"}

    def test_multiline_args(self):
        phrase, args = _normalize("restart service\nservice=sshd\nhost=web01")
        assert phrase == "restart service"
        assert args == {"service": "sshd", "host": "web01"}

    def test_empty_input(self):
        phrase, args = _normalize("")
        assert phrase == ""
        assert args == {}

    def test_strips_punctuation(self):
        phrase, args = _normalize('"show disk usage"')
        assert phrase == "show disk usage"

    def test_truncates_long_phrase(self):
        phrase, args = _normalize(" ".join(["word"] * 15))
        assert len(phrase.split()) == 8


# ---------------------------------------------------------------------------
# Extraction dataclass
# ---------------------------------------------------------------------------


class TestExtraction:
    def test_default_args_is_none(self):
        e = Extraction(phrase="test", tokens_in=0, tokens_out=0, backend="test")
        assert e.args is None

    def test_args_stored(self):
        e = Extraction(
            phrase="show logs for container",
            tokens_in=10,
            tokens_out=5,
            backend="passthrough",
            args={"container": "nginx"},
        )
        assert e.args == {"container": "nginx"}


# ---------------------------------------------------------------------------
# Integration: passthrough extract with args
# ---------------------------------------------------------------------------


class TestPassthroughExtract:
    """Test the extract() function with passthrough backend and arg detection."""

    def test_passthrough_extracts_phrase(self):
        from src.lever_runner.intent_extractor import extract

        result = extract("show disk usage", backend="passthrough")
        assert "show disk usage" in result.phrase
        assert result.backend == "passthrough"
        # No args for a simple request
        assert result.args is None or result.args == {}

    def test_passthrough_empty_request(self):
        from src.lever_runner.intent_extractor import extract

        result = extract("", backend="passthrough")
        assert result.phrase == ""
        assert result.tokens_in == 0


# ---------------------------------------------------------------------------
# Orchestrator integration with mocked store/extractor
# ---------------------------------------------------------------------------


class TestOrchestratorWithParams:
    """Test the orchestrator's handling of parameterized commands."""

    def test_template_command_with_args(self):
        """When a template command is matched and args are extracted,
        the command should be substituted before execution."""
        from src.lever_runner.orchestrator import do
        from src.lever_runner.store import Match

        mock_match = Match(
            id="test-id",
            intent_phrase="show logs for {{container}}",
            command="docker logs --tail 100 {{container}}",
            trust_score=75.0,
            success_count=5,
            failure_count=0,
            score=0.1,
            similarity=0.9,
        )

        mock_extraction = MagicMock()
        mock_extraction.phrase = "show logs for container"
        mock_extraction.tokens_in = 10
        mock_extraction.tokens_out = 5
        mock_extraction.backend = "passthrough"
        mock_extraction.args = {"container": "nginx"}

        mock_run_result = MagicMock()
        mock_run_result.ok = True
        mock_run_result.exit_code = 0
        mock_run_result.stdout = "nginx logs here"
        mock_run_result.stderr = ""
        mock_run_result.duration_sec = 0.5

        mock_store = MagicMock()
        mock_store.find_best.return_value = [mock_match]

        with (
            patch("src.lever_runner.orchestrator.extract_intent", return_value=mock_extraction),
            patch("src.lever_runner.orchestrator.run_command", return_value=mock_run_result) as mock_run,
            patch("src.lever_runner.orchestrator.token_logger"),
        ):
            result = do(
                "show logs for nginx",
                store=mock_store,
            )

        assert result.ok is True
        assert result.args == {"container": "nginx"}
        mock_run.assert_called_once_with("docker logs --tail 100 nginx")

    def test_template_command_without_args_fails(self):
        """When a template command is matched but no args are extracted,
        the result should be an error."""
        from src.lever_runner.orchestrator import do
        from src.lever_runner.store import Match

        mock_match = Match(
            id="test-id",
            intent_phrase="show logs for {{container}}",
            command="docker logs --tail 100 {{container}}",
            trust_score=75.0,
            success_count=5,
            failure_count=0,
            score=0.1,
            similarity=0.9,
        )

        mock_extraction = MagicMock()
        mock_extraction.phrase = "show logs for container"
        mock_extraction.tokens_in = 10
        mock_extraction.tokens_out = 5
        mock_extraction.backend = "passthrough"
        mock_extraction.args = None  # No args extracted

        mock_store = MagicMock()
        mock_store.find_best.return_value = [mock_match]

        with (
            patch("src.lever_runner.orchestrator.extract_intent", return_value=mock_extraction),
            patch("src.lever_runner.orchestrator.token_logger"),
        ):
            result = do(
                "show logs for",
                store=mock_store,
            )

        assert result.ok is False
        assert "requires arguments" in result.error
        assert "container" in result.error

    def test_non_template_command_unchanged(self):
        """When a non-template command is matched, it should run as-is."""
        from src.lever_runner.orchestrator import do
        from src.lever_runner.store import Match

        mock_match = Match(
            id="test-id",
            intent_phrase="show disk usage",
            command="df -h",
            trust_score=80.0,
            success_count=10,
            failure_count=0,
            score=0.1,
            similarity=0.95,
        )

        mock_extraction = MagicMock()
        mock_extraction.phrase = "show disk usage"
        mock_extraction.tokens_in = 10
        mock_extraction.tokens_out = 5
        mock_extraction.backend = "passthrough"
        mock_extraction.args = None

        mock_run_result = MagicMock()
        mock_run_result.ok = True
        mock_run_result.exit_code = 0
        mock_run_result.stdout = "Filesystem Size"
        mock_run_result.stderr = ""

        mock_store = MagicMock()
        mock_store.find_best.return_value = [mock_match]

        with (
            patch("src.lever_runner.orchestrator.extract_intent", return_value=mock_extraction),
            patch("src.lever_runner.orchestrator.run_command", return_value=mock_run_result) as mock_run,
            patch("src.lever_runner.orchestrator.token_logger"),
        ):
            result = do("check disk", store=mock_store)

        assert result.ok is True
        mock_run.assert_called_once_with("df -h")

    def test_template_with_invalid_arg_rejected(self):
        """When extracted args contain shell metacharacters, the substitution
        should fail with a validation error."""
        from src.lever_runner.orchestrator import do
        from src.lever_runner.store import Match

        mock_match = Match(
            id="test-id",
            intent_phrase="show logs for {{container}}",
            command="docker logs --tail 100 {{container}}",
            trust_score=75.0,
            success_count=5,
            failure_count=0,
            score=0.1,
            similarity=0.9,
        )

        mock_extraction = MagicMock()
        mock_extraction.phrase = "show logs for container"
        mock_extraction.tokens_in = 10
        mock_extraction.tokens_out = 5
        mock_extraction.backend = "passthrough"
        mock_extraction.args = {"container": "nginx; rm -rf /"}

        mock_store = MagicMock()
        mock_store.find_best.return_value = [mock_match]

        with (
            patch("src.lever_runner.orchestrator.extract_intent", return_value=mock_extraction),
            patch("src.lever_runner.orchestrator.token_logger"),
        ):
            result = do("show logs for evil", store=mock_store)

        assert result.ok is False
        assert "argument substitution failed" in result.error
        assert "disallowed characters" in result.error


# ---------------------------------------------------------------------------
# Teach with template syntax
# ---------------------------------------------------------------------------


class TestTeachTemplate:
    """Test that teach() stores template commands correctly."""

    def test_teach_stores_template(self):
        from src.lever_runner.orchestrator import teach

        mock_store = MagicMock()
        mock_store.teach.return_value = "test-row-id"

        row_id = teach(
            "show logs for {{container}}",
            "docker logs --tail 100 {{container}}",
            store=mock_store,
        )

        assert row_id == "test-row-id"
        mock_store.teach.assert_called_once_with(
            "show logs for {{container}}",
            "docker logs --tail 100 {{container}}",
            trust=None,
        )

    def test_teach_regular_command(self):
        from src.lever_runner.orchestrator import teach

        mock_store = MagicMock()
        mock_store.teach.return_value = "test-row-id"

        row_id = teach("show disk usage", "df -h", store=mock_store)

        assert row_id == "test-row-id"
        mock_store.teach.assert_called_once_with(
            "show disk usage",
            "df -h",
            trust=None,
        )
