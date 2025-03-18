# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.8] - 2025-03-18

### Added

- Add `project` to `JobDescription`

## [0.0.7] - 2025-01-21

### Fixed

- Change `typer` to a dev dependency

## [0.0.6] - 2025-01-08

### Added

- Add `progress` arg to `Job.{wait,wait_all,result,result_all}` defaulting to `True`
  - If `False`, these methods will not output to stdout during execution or on job completion
- Add publish GH action

### Changed

- Change `makefile` to use `uv`

## [0.0.5] - 2024-09-24

### Changed

- Change refresh rate to 1Hz in `_pbs_wait_for_jobs` and remove progress spinner

### Fixed

- Fix `CHANGELOG.md` URL in package metadata

## [0.0.4] - 2024-09-24

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

[unreleased]: https://github.com/MaterialsPhysicsANU/pbspy/compare/v0.0.8...HEAD
[0.0.8]: https://github.com/MaterialsPhysicsANU/pbspy/releases/tag/v0.0.8
[0.0.7]: https://github.com/MaterialsPhysicsANU/pbspy/releases/tag/v0.0.7
[0.0.6]: https://github.com/MaterialsPhysicsANU/pbspy/releases/tag/v0.0.6
[0.0.5]: https://github.com/MaterialsPhysicsANU/pbspy/releases/tag/v0.0.5
[0.0.4]: https://github.com/MaterialsPhysicsANU/pbspy/releases/tag/v0.0.4
[0.0.3]: https://github.com/MaterialsPhysicsANU/pbspy/releases/tag/v0.0.3
[0.0.2]: https://github.com/MaterialsPhysicsANU/pbspy/releases/tag/v0.0.2
[0.0.1]: https://github.com/MaterialsPhysicsANU/pbspy/releases/tag/v0.0.1
