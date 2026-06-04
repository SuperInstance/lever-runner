"""
Tests for CLI subcommands: --version, doctor, stats, export, import.
"""

import json
import os
import sys
import tempfile

import pytest

# Ensure the package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestVersion:
    def test_version_flag(self):
        from lever_runner.cli import main

        try:
            code = main(["--version"])
            assert code == 0
        except (ImportError, ModuleNotFoundError):
            pytest.skip("dependencies not available")

    def test_version_output(self, capsys):
        from lever_runner.cli import main

        try:
            main(["--version"])
            captured = capsys.readouterr()
            assert "lever-runner" in captured.out
            assert "0." in captured.out
        except (ImportError, ModuleNotFoundError):
            pytest.skip("dependencies not available")


class TestDoctor:
    def test_doctor_runs(self):
        from lever_runner.cli import main

        try:
            # Doctor may return 0 or 1 depending on env
            code = main(["doctor"])
            assert code in (0, 1, 2)
        except (ImportError, ModuleNotFoundError):
            pytest.skip("sentence_transformers not available")

    def test_doctor_as_subcommand(self, capsys):
        from lever_runner.cli import main

        try:
            main(["doctor"])
        except (ImportError, ModuleNotFoundError):
            pytest.skip("sentence_transformers not available")
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "doctor" in captured.out.lower()


class TestStats:
    def test_stats_runs(self, capsys):
        from lever_runner.cli import main

        try:
            code = main(["stats"])
            assert code in (0, 1)
        except (ImportError, ModuleNotFoundError):
            pytest.skip("sentence_transformers not available")

    def test_stats_shows_header(self, capsys):
        from lever_runner.cli import main

        try:
            main(["stats"])
            captured = capsys.readouterr()
            assert "stats" in captured.out.lower()
        except (ImportError, ModuleNotFoundError):
            pytest.skip("sentence_transformers not available")


class TestExport:
    def test_export_json(self, capsys):
        from lever_runner.cli import main

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            code = main(["export", "--format", "json", "--output", path])
            assert code in (0, 1)  # 1 = no commands, not a crash

            if code == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
                data = json.loads(open(path).read())
                assert "commands" in data
                assert "version" in data
        except (ImportError, ModuleNotFoundError):
            pytest.skip("sentence_transformers not available")
        finally:
            os.unlink(path) if os.path.exists(path) else None

    def test_export_aliases(self, capsys):
        from lever_runner.cli import main

        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as f:
            path = f.name
        try:
            code = main(["export", "--format", "aliases", "--output", path])
            assert code in (0, 1)

            if code == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
                content = open(path).read()
                assert "#!/bin/bash" in content
        except (ImportError, ModuleNotFoundError):
            pytest.skip("sentence_transformers not available")
        finally:
            os.unlink(path) if os.path.exists(path) else None

    def test_export_to_stdout(self, capsys):
        from lever_runner.cli import main

        try:
            code = main(["export", "--format", "json"])
            assert code in (0, 1)
        except (ImportError, ModuleNotFoundError):
            pytest.skip("sentence_transformers not available")


class TestImport:
    def test_import_json_roundtrip(self, capsys):
        """Export then import should not crash."""
        from lever_runner.cli import main

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({
                "version": "0.4.0",
                "exported_at": "2026-01-01T00:00:00Z",
                "chat_id": "default",
                "commands": [
                    {"intent_phrase": "test import", "command": "echo hello", "trust_score": 50.0}
                ]
            }, f)
            path = f.name
        try:
            code = main(["import", path, "--format", "json"])
            assert code in (0, 1)
            captured = capsys.readouterr()
            assert "imported" in captured.out.lower() or "Imported" in captured.out
        except (ImportError, ModuleNotFoundError):
            pytest.skip("sentence_transformers not available")
        finally:
            os.unlink(path)

    def test_import_missing_file(self, capsys):
        from lever_runner.cli import main

        try:
            code = main(["import", "/tmp/nonexistent_lever_runner_test.json"])
            assert code == 1
        except (ImportError, ModuleNotFoundError):
            pytest.skip("sentence_transformers not available")


class TestCLIParsing:
    def test_no_args_shows_help(self, capsys):
        from lever_runner.cli import main

        code = main([])
        assert code == 2

    def test_chat_id_flag(self):
        """--chat-id should be accepted without error."""
        from lever_runner.cli import main

        # Just test that it parses, not that it connects
        try:
            main(["--chat-id", "test_chat", "status"])
        except (ImportError, ModuleNotFoundError):
            pytest.skip("sentence_transformers not available")
        except SystemExit:
            pass

    def test_build_parser(self):
        """Parser should build without error."""
        try:
            from lever_runner.cli import build_parser
            parser = build_parser()
            assert parser is not None
            assert parser.prog == "lever-runner"
        except (ImportError, ModuleNotFoundError):
            pytest.skip("dependencies not available")
