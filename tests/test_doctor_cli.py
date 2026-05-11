from typer.testing import CliRunner

from sidequests.cli.main import app
from sidequests.cli.doctor import DoctorChecker


def test_doctor_command_is_registered():
    result = CliRunner().invoke(app, ["doctor", "--help"])

    assert result.exit_code == 0
    assert "repair" in result.output


def test_doctor_checker_records_python_version():
    checker = DoctorChecker()
    checker._check_python_version()

    assert checker.checks
    assert checker.checks[0][0] == "Python Version"
