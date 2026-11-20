from typer.testing import CliRunner

from revenant.cli import app


def test_help_exits_0_and_lists_exhume() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "exhume" in result.output
