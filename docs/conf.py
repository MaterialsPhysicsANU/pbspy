project = "pbspy"
extensions = ["myst_parser"]
source_suffix = [".rst", ".md"]
extensions = [
    "autodoc2",
    "sphinx.ext.napoleon",
]
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
autodoc2_packages = [
    "../src/pbspy",
]
autodoc2_module_all_regexes = [
    r".*",
]
