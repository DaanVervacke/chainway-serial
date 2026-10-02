"""Sphinx configuration for the chainway-serial documentation."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

project = "chainway-serial"
author = "Daan Vervacke"
copyright = "2026, Daan Vervacke"  # noqa: A001
try:
    release = _version("chainway-serial")
except PackageNotFoundError:
    release = "0.0.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

html_theme = "furo"
