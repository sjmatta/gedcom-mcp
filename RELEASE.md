# Release Checklist

Manual checklist for publishing releases of GEDCOM MCP Server.

## Pre-Release Verification

- [ ] All tests pass: `uv run poe test`
- [ ] Linting passes: `uv run poe lint`
- [ ] Format check passes: `uv run ruff format --check .`
- [ ] Type checking passes: `uv run poe typecheck`
- [ ] Pre-commit hooks pass: `uv run pre-commit run --all-files`
- [ ] No uncommitted changes: `git status`
- [ ] On main branch: `git branch` shows `* main`
- [ ] Local main is up to date with origin: `git pull origin main`

## Version Update

- [ ] Update version in `pyproject.toml` (e.g., `version = "1.0.1"`)
- [ ] Update `CHANGELOG.md`:
  - Set release date: `## [X.Y.Z] - YYYY-MM-DD`
  - Ensure all changes are documented
  - Add compare link at bottom if needed
- [ ] Commit version bump:
  ```bash
  git add pyproject.toml CHANGELOG.md
  git commit -m "Release vX.Y.Z"
  ```

## Create Git Tag

- [ ] Create annotated tag:
  ```bash
  git tag -a vX.Y.Z -m "Release X.Y.Z"
  ```
- [ ] Push commits and tags:
  ```bash
  git push origin main
  git push origin vX.Y.Z
  ```

## Build Package

- [ ] Clean previous builds:
  ```bash
  rm -rf dist/ build/ *.egg-info
  ```
- [ ] Build distributions:
  ```bash
  uv build
  ```
- [ ] Verify build artifacts exist:
  ```bash
  ls -lh dist/
  # Should see: gedcom_server-X.Y.Z-py3-none-any.whl and .tar.gz
  ```
- [ ] Check package metadata:
  ```bash
  uv tool install twine
  uv run twine check dist/*
  ```
- [ ] Verify LICENSE is included:
  ```bash
  tar -tzf dist/gedcom_server-X.Y.Z.tar.gz | grep LICENSE
  ```

## Test Package Locally

- [ ] Test installation from wheel:
  ```bash
  uvx --from dist/gedcom_server-X.Y.Z-py3-none-any.whl gedcom-server --help
  ```
- [ ] Verify version number:
  ```bash
  uvx --from dist/gedcom_server-X.Y.Z-py3-none-any.whl gedcom-server --version
  # (if version command exists)
  ```

## Publish to PyPI

⚠️ **Warning**: PyPI uploads are permanent and cannot be deleted!

- [ ] Ensure you have PyPI credentials configured
- [ ] Upload to PyPI:
  ```bash
  uv run twine upload dist/*
  ```
- [ ] Enter PyPI username and password when prompted
- [ ] Verify upload success message

## Create GitHub Release

- [ ] Go to: https://github.com/sjmatta/gedcom-mcp/releases/new
- [ ] Select tag: `vX.Y.Z`
- [ ] Release title: `vX.Y.Z` or `Version X.Y.Z`
- [ ] Description: Copy from `CHANGELOG.md` (the section for this version)
- [ ] Attach files:
  - Upload `dist/gedcom_server-X.Y.Z-py3-none-any.whl`
  - Upload `dist/gedcom_server-X.Y.Z.tar.gz`
- [ ] For major releases: Check "Set as latest release"
- [ ] For patch releases: Uncheck "Set as latest release" if appropriate
- [ ] Click "Publish release"

## Post-Release Verification

- [ ] Verify PyPI page: https://pypi.org/project/gedcom-server/
  - [ ] Version number is correct
  - [ ] README renders correctly
  - [ ] Links work (Homepage, Repository, etc.)
  - [ ] License is shown as MIT
  - [ ] Classifiers are correct
- [ ] Test installation from PyPI:
  ```bash
  uvx gedcom-server@X.Y.Z --help
  ```
- [ ] Verify GitHub release page looks correct
- [ ] Verify GitHub Actions CI passed for the release commit

## Prepare for Next Development

- [ ] Update version in `pyproject.toml` to next dev version (e.g., `1.0.2-dev`)
- [ ] Add new `[Unreleased]` section to `CHANGELOG.md`:
  ```markdown
  ## [Unreleased]

  ### Added

  ### Changed

  ### Fixed

  ## [X.Y.Z] - YYYY-MM-DD
  ...
  ```
- [ ] Commit:
  ```bash
  git add pyproject.toml CHANGELOG.md
  git commit -m "Prepare for vX.Y.Z+1 development"
  git push origin main
  ```

## Announcement (Optional)

- [ ] Update project homepage if needed
- [ ] Post announcement on relevant platforms
- [ ] Update examples or documentation that reference version numbers

## Troubleshooting

### Build fails

- Check that all tests pass
- Verify `pyproject.toml` syntax
- Ensure LICENSE file exists
- Check that all files are committed

### Twine upload fails

- Verify PyPI credentials
- Check network connection
- Ensure version doesn't already exist on PyPI
- Try with `--verbose` flag for more info:
  ```bash
  uv run twine upload --verbose dist/*
  ```

### Package installs but doesn't work

- Test in clean virtual environment
- Check that all dependencies are listed in `pyproject.toml`
- Verify entry point in `[project.scripts]`

### GitHub release doesn't show artifacts

- Manually upload files after creating release
- Check file size limits (100MB for GitHub releases)
- Verify you have write access to repository

## Notes

- **Semantic Versioning**: Follow semver (major.minor.patch)
  - Major: Breaking changes
  - Minor: New features (backwards compatible)
  - Patch: Bug fixes (backwards compatible)

- **Release Frequency**: Release when ready, no fixed schedule
  - Critical bugs: Patch release ASAP
  - New features: Minor release when feature is complete
  - Breaking changes: Major release with migration guide

- **Branch Strategy**: All releases from `main` branch
  - No release branches for 1.x
  - May add release branches for 2.x if needed

- **Hotfixes**: For critical bugs:
  1. Fix on main
  2. Cherry-pick to release branch if needed
  3. Release patch version immediately
