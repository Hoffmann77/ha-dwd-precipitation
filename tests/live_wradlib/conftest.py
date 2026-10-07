"""Print the per-location results table, and put it in the GitHub job summary."""

import os

from tests.live_wradlib.report import render


def pytest_terminal_summary(terminalreporter):
    table = render()
    if not table:
        return
    terminalreporter.write_sep("=", "DWD values per location")
    terminalreporter.write(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(table)
