from configparser import ConfigParser
from typing import Dict
import os
import pathlib
import tempfile

import pytest

import yoyo.config


def to_dict(parser: ConfigParser) -> Dict[str, Dict[str, str]]:
    return {section: dict(parser[section]) for section in parser}


def _test_files(files, expected):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = pathlib.Path(tmpdir)
        for path, data in files.items():
            with (tmpdir_path / path).open("w") as f:
                f.write(data)
        saved = os.getcwd()
        os.chdir(tmpdir)
        try:
            config = yoyo.config.read_config(
                str(tmpdir_path / next(iter(sorted(files))))
            )
        finally:
            os.chdir(saved)
        assert to_dict(config) == expected


class TestInheritance:
    def test_read_config_returns_empty_on_None(self):
        config = yoyo.config.read_config(None)
        assert to_dict(config) == {"DEFAULT": {}}

    def test_inherit_one(self):
        _test_files(
            {
                "a.ini": "[DEFAULT]\n%inherit = b.ini\nx=a\ny=a\n",
                "b.ini": "[DEFAULT]\ny = b\nz = b\n",
            },
            {"DEFAULT": {"x": "a", "y": "a", "z": "b"}},
        )

    def test_inherit_many(self):
        _test_files(
            {
                "a.ini": (
                    "[DEFAULT]\n"
                    "%inherit = b.ini c.ini\n"
                    "v = a\n"
                    "w = a\n"
                    "x = a\n"
                ),
                "b.ini": "[DEFAULT]\nw = b\nx = b\ny = b",
                "c.ini": "[DEFAULT]\nx = c\ny = c\nz = c",
            },
            {"DEFAULT": {"v": "a", "w": "a", "x": "a", "y": "b", "z": "c"}},
        )

    def test_include_one(self):
        _test_files(
            {
                "a.ini": "[DEFAULT]\n%include = b.ini\nx=a\ny=a\n",
                "b.ini": "[DEFAULT]\ny = b\nz = b\n",
            },
            {"DEFAULT": {"x": "a", "y": "b", "z": "b"}},
        )

    def test_include_many(self):
        _test_files(
            {
                "a.ini": (
                    "[DEFAULT]\n"
                    "%include = b.ini c.ini\n"
                    "v = a\n"
                    "w = a\n"
                    "x = a\n"
                ),
                "b.ini": "[DEFAULT]\nw = b\nx = b\ny = b",
                "c.ini": "[DEFAULT]\nx = c\ny = c\nz = c",
            },
            {"DEFAULT": {"v": "a", "w": "b", "x": "c", "y": "c", "z": "c"}},
        )

    def test_nested_inherit(self):
        _test_files(
            {
                "a.ini": (
                    "[DEFAULT]\n"
                    "%inherit = b.ini\n"
                    "v = a\n"
                    "w = a\n"
                    "x = a\n"
                ),
                "b.ini": (
                    "[DEFAULT]\n"
                    "%inherit = c.ini\n"
                    "w = b\n"
                    "x = b\n"
                    "y = b\n"
                ),
                "c.ini": "[DEFAULT]\nx = c\ny = c\nz = c",
            },
            {"DEFAULT": {"v": "a", "w": "a", "x": "a", "y": "b", "z": "c"}},
        )

    def test_nested_include(self):
        _test_files(
            {
                "a.ini": (
                    "[DEFAULT]\n"
                    "%include = b.ini\n"
                    "v = a\n"
                    "w = a\n"
                    "x = a\n"
                ),
                "b.ini": (
                    "[DEFAULT]\n"
                    "%include = c.ini\n"
                    "w = b\n"
                    "x = b\n"
                    "y = b\n"
                ),
                "c.ini": "[DEFAULT]\nx = c\ny = c\nz = c",
            },
            {"DEFAULT": {"v": "a", "w": "b", "x": "c", "y": "c", "z": "c"}},
        )

    def test_it_raises_on_not_found(self):
        with pytest.raises(FileNotFoundError):
            _test_files(
                {"a.ini": "[DEFAULT]\n%inherit = b.ini\n"}, {"DEFAULT": {}},
            )

    def test_it_ignores_not_found(self):
        _test_files(
            {"a.ini": "[DEFAULT]\n%inherit = ?b.ini\n"}, {"DEFAULT": {}},
        )

    def test_it_traps_circular_references(self):
        with pytest.raises(yoyo.config.CircularReferenceError):
            _test_files(
                {
                    "a.ini": "[DEFAULT]\n%inherit = b.ini\n",
                    "b.ini": "[DEFAULT]\n%inherit = a.ini\n",
                },
                {"DEFAULT": {}},
            )

    def test_it_traps_deep_circular_references(self):
        with pytest.raises(yoyo.config.CircularReferenceError):
            _test_files(
                {
                    "a.ini": "[DEFAULT]\n%include = b.ini c.ini\n",
                    "b.ini": "[DEFAULT]\n%include = c.ini\n",
                    "c.ini": "[DEFAULT]\n%include = a.ini\n",
                },
                {"DEFAULT": {}},
            )

    def test_it_allows_acyclic_references(self):
        _test_files(
            {
                "a.ini": "[DEFAULT]\n%include = b.ini c.ini\nw = a\nx = a\n",
                "b.ini": "[DEFAULT]\n%include = c.ini\nx = b\ny = b",
                "c.ini": "[DEFAULT]\ny = c\nz = c\n",
            },
            {"DEFAULT": {"w": "a", "x": "b", "y": "c", "z": "c"}},
        )


class TestInterpolation:
    def test_it_interpolates_environment_variables(self):
        os.environ["yoyo_test_env_var"] = "foo"
        try:
            _test_files(
                {"a.ini": "[DEFAULT]\nx=%(yoyo_test_env_var)s"},
                {"DEFAULT": {"x": "foo"}},
            )
        finally:
            del os.environ["yoyo_test_env_var"]

    def test_it_folds_environment_variable_case(self):
        os.environ["YOYO_TEST_ENV_VAR"] = "foo"
        try:
            _test_files(
                {"a.ini": "[DEFAULT]\nx=%(yoyo_test_env_var)s"},
                {"DEFAULT": {"x": "foo"}},
            )
        finally:
            del os.environ["YOYO_TEST_ENV_VAR"]
