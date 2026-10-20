"""Readme: the flags, the actions and the variables that it names must match the code.

Each test reads the help text of a real CLI, so a flag that a parser gains or loses fails the
suite until the readme names it too.
"""
import contextlib
import io
import re
import sys
from pathlib import Path

import pytest

import push
import r2

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def help_of(module, monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "argv", [f"{module.__name__}.py", "--help"])
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit):
        module.main()
    return out.getvalue()


def flags(text):
    return set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", text)) - {"--help"}


@pytest.mark.parametrize("module", [push, r2])
def test_the_readme_names_every_flag_of_the_cli(module, monkeypatch):
    assert flags(help_of(module, monkeypatch)) - flags(README) == set()


def test_every_flag_in_the_readme_exists_in_a_cli(monkeypatch):
    known = flags(help_of(push, monkeypatch)) | flags(help_of(r2, monkeypatch))
    assert flags(README) - known == set()


def test_the_readme_names_every_action_of_r2(monkeypatch):
    choices = re.search(r"\{([a-z,]+)\}", help_of(r2, monkeypatch))
    assert choices, "the help of r2.py lists no actions"
    actions = set(choices.group(1).split(","))
    assert actions - set(re.findall(r"r2\.py ([a-z]+)", README)) == set()


def test_the_readme_lists_exactly_the_variables_that_the_code_reads():
    code = "".join((ROOT / name).read_text(encoding="utf-8") for name in ("r2.py", "push.py"))
    assert set(re.findall(r"\bR2_[A-Z_]+\b", code)) == set(re.findall(r"`(R2_[A-Z_]+)`", README))
