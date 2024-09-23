# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add `JobDescription.add_commands()`

### Fixed

- Fix `JobDescription.from_nodes()` not scaling `jobfs` with the number of nodes

## [0.0.3] - 2024-09-08

### Added

- Add links to pypi and docs in README

### Fixed

- Handle missing output/error file

## [0.0.2] - 2024-09-08

### Added

- Add `str` support to `JobDescription.add_command()`

### Changed

- Switch to the MIT license from the Apache Software License, Version 2.0
- Use Python version badge from `pyproject.toml`

### Fixed

- Fix `pyproject.toml` project description to match README/docs
- Cleanup outputs in makefile `docs`, `build`, and `publish`

## [0.0.1] - 2024-09-08

### Added

- Initial release

[unreleased]: https://github.com/MaterialsPhysicsANU/pbspy/compare/v0.0.3...HEAD
[0.0.3]: https://github.com/MaterialsPhysicsANU/pbspy/releases/tag/v0.0.3
[0.0.2]: https://github.com/MaterialsPhysicsANU/pbspy/releases/tag/v0.0.2
[0.0.1]: https://github.com/MaterialsPhysicsANU/pbspy/releases/tag/v0.0.1
