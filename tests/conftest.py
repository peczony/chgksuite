import pytest


def pytest_addoption(parser):
    parser.addoption("--tex", action="store_true", help="run tex tests")


def pytest_runtest_setup(item):
    if "tex" in item.keywords and not item.config.getoption("--tex"):
        pytest.skip("need --tex option to run this test")
