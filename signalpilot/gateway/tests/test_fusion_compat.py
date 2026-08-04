"""dbt Fusion compatibility tests.

FUSION_PARSE_ERROR / FUSION_RUN_ERROR / FUSION_VERSION are REAL outputs
captured from dbt-fusion 2.0.0-preview.202 in a docker probe (2026-07-22).
The [warning] fixture is SYNTHESIZED by analogy with the captured [error]
shape (no warning was emitted during the probe) — treat its exact format as
unverified. dbt-core fixtures sit alongside to prove both engines flow
through the same code paths.

The version parser is tested against the REAL notebook-server module
(loaded standalone by file path — version_parse.py is dependency-free for
exactly this reason), not a hand-copied mirror.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess

from gateway.dbt.error_parse import parse_dbt_error
from gateway.dbt.validator import _ERROR_LINE, _WARNING_LINE, _build_result, _detect_degradation_mode

FUSION_VERSION = "dbt-fusion 2.0.0-preview.202"

FUSION_PARSE_ERROR = """dbt-fusion 2.0.0-preview.202
   Loading ~/.dbt/profiles.yml

=================== Errors and Warnings ====================
[error] [DependencyNotFound (dbt1048)]: Ref 'missing_model' not found in project. Searched for 'fusion_probe.missing_model, missing_model'
  --> models/broken.sql:1:15

==================== Execution Summary =====================
Finished 'parse' with 1 error [282ms]
"""

FUSION_RUN_ERROR = """=================== Errors and Warnings ====================
[error] [DbDriverFailed (dbt1308)]: Database Error in model bad (target/run/fusion_probe/models/bad.sql)
  Catalog Error: Table with name ok_model_typo does not exist!
  Did you mean "ok_model"?

  LINE 5:     select nonexistent_col from ok_model_typo
                                          ^
  (in run/fusion_probe/models/bad.sql)
"""

CORE_PARSE_WARNING = "\x1b[0m14:56:54  [WARNING]: Did not find matching node for patch with name 'ghost_model'"
CORE_PARSE_ERROR = "\x1b[0m14:56:55  [ERROR]: Compilation Error in model foo"


def _load_version_parse():
    """Load the REAL notebook-server version parser by file path."""
    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "notebook-server"
        / "signalpilot"
        / "_dbt"
        / "version_parse.py"
    )
    spec = importlib.util.spec_from_file_location("nb_version_parse", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMarkerRegexes:
    def test_fusion_error_marker_matches(self):
        line = "[error] [DependencyNotFound (dbt1048)]: Ref 'missing_model' not found in project."
        m = _ERROR_LINE.search(line)
        assert m
        assert "Ref 'missing_model' not found" in m.group(1)

    def test_fusion_warning_marker_matches(self):
        # synthesized-by-analogy fixture (see module docstring)
        m = _WARNING_LINE.search("[warning] [DeprecatedConfig (dbt0999)]: config 'foo' is deprecated")
        assert m and "deprecated" in m.group(1)

    def test_core_uppercase_markers_still_match(self):
        assert _ERROR_LINE.search("[ERROR]: Compilation Error in model foo")
        assert _WARNING_LINE.search("[WARNING]: Did not find matching node for patch with name 'x'")


class TestBuildResult:
    def _result(self, output: str, returncode: int, project_dir=None):
        completed = subprocess.CompletedProcess(
            args=["dbt", "parse"], returncode=returncode, stdout=output, stderr=""
        )
        return _build_result(completed, project_dir or pathlib.Path("."), 100.0)

    def test_fusion_parse_error_captured(self):
        result = self._result(FUSION_PARSE_ERROR, returncode=1)
        assert not result.success
        assert result.error_count >= 1
        assert any("missing_model" in e for e in result.errors)

    def test_fusion_run_error_captured(self):
        result = self._result(FUSION_RUN_ERROR, returncode=1)
        assert not result.success
        assert any("Database Error in model bad" in e for e in result.errors)

    def test_core_ansi_warning_captured(self):
        result = self._result(CORE_PARSE_WARNING, returncode=0)
        assert result.warning_count == 1
        assert result.orphan_patches == ["ghost_model"]

    def test_core_error_captured(self):
        result = self._result(CORE_PARSE_ERROR, returncode=1)
        assert not result.success
        assert any("Compilation Error" in e for e in result.errors)


class TestDegradationMode:
    def test_fusion_banner_does_not_mean_profile_missing(self):
        """Fusion prints 'Loading ~/.dbt/profiles.yml' on EVERY run — a
        missing-ref parse error must not classify as profile_missing."""
        mode = _detect_degradation_mode(FUSION_PARSE_ERROR, 1, pathlib.Path("."))
        assert mode != "profile_missing"
        assert mode == "parse_failed"  # DependencyNotFound is a parse-stage code

    def test_core_profile_missing_still_detected(self):
        out = "Runtime Error\n  Could not find profile named 'adventureworks'"
        assert _detect_degradation_mode(out, 1, pathlib.Path(".")) == "profile_missing"


class TestDbtErrorParser:
    """The pure parser behind the dbt_error_parser MCP tool, on REAL fixtures."""

    def test_fusion_parse_error(self):
        parsed = parse_dbt_error(FUSION_PARSE_ERROR)
        assert parsed.error_type == "DependencyNotFound (dbt1048)"
        assert parsed.location == "models/broken.sql line 1, col 15"
        assert "Ref 'missing_model' not found" in parsed.message

    def test_fusion_run_error(self):
        parsed = parse_dbt_error(FUSION_RUN_ERROR)
        assert parsed.model == "bad"
        assert "DbDriverFailed (dbt1308)" in parsed.error_type
        assert "Database Error" in parsed.error_type
        # uppercase 'LINE 5:' from the DB error is matched case-insensitively
        assert parsed.location == "line 5"
        assert "ok_model_typo" in parsed.suggested_fix

    def test_core_error(self):
        out = 'Database Error in model fct_orders (models/fct_orders.sql)\n  column "amount" does not exist\n  LINE 12: select amount'
        parsed = parse_dbt_error(out)
        assert parsed.model == "fct_orders"
        assert parsed.error_type == "Database Error"
        assert parsed.location == "line 12"
        assert "amount" in parsed.suggested_fix


class TestFusionVersionParsing:
    def test_fusion_version(self):
        mod = _load_version_parse()
        assert mod.parse_dbt_version(FUSION_VERSION) == "fusion-2.0.0-preview.202"

    def test_core_version(self):
        mod = _load_version_parse()
        out = "Core:\n  - installed: 1.8.2\n  - latest:    1.8.2"
        assert mod.parse_dbt_version(out) == "1.8.2"

    def test_no_version(self):
        mod = _load_version_parse()
        assert mod.parse_dbt_version("garbage output") is None

    def test_runner_module_compiles(self):
        """Backstop: the real runner.py must at least be syntactically valid."""
        import py_compile

        runner = (
            pathlib.Path(__file__).resolve().parents[2]
            / "notebook-server"
            / "signalpilot"
            / "_dbt"
            / "runner.py"
        )
        py_compile.compile(str(runner), doraise=True)
