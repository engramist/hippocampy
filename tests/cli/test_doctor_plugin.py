# tests/cli/test_doctor_plugin.py
from campy.cli.doctor import DoctorChecker

def test_doctor_has_plugin_check():
    """DoctorChecker should have a check_plugin_status method."""
    checker = DoctorChecker.__new__(DoctorChecker)
    assert hasattr(checker, "_check_plugin_status") or hasattr(checker, "check_plugin_status")
