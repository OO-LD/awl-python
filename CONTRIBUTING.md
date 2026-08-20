# Contributing to awl-python

## Setup

```bash
make install
```

Creates the virtual environment and installs the git hooks. Run it once after cloning.

## Before you push

```bash
make ci
```

Runs `check`, `test` and `docs-test` in the order CI does, so a green run here means a green run there. See the [README](README.md) for the individual targets.

## Commit messages

This repository uses [Conventional Commits](https://www.conventionalcommits.org/). This is not a style preference: the version number, the changelog and the release notes are **derived** from these messages, so a wrong type produces a wrong version.

```text
<type>(<optional scope>): <description>
```

| Type | Use for | Release effect |
| --- | --- | --- |
| `feat` | A new capability | Minor version bump |
| `fix` | A bug fix | Patch version bump |
| `docs` | Documentation only | None |
| `test` | Tests only | None |
| `refactor` | Behaviour-preserving restructuring | None |
| `perf` | A performance improvement | Patch version bump |
| `build` | Build system or dependencies | None |
| `ci` | CI configuration | None |
| `chore` | Anything else | None |

A breaking change is either `feat!:` or a `BREAKING CHANGE:` footer, and bumps the major version.

Write the description in the imperative and lowercase, with no trailing full stop:

```text
feat: add a retry policy to the client
fix(parser): handle an empty payload
docs: explain the release process
```

The `commit-msg` hook rejects anything else locally, before it reaches CI. If a commit is refused, fix the message and commit again; nothing was lost.

## Pull requests

Work on a branch and open a pull request. Keep the pull request title conventional too, since a squash merge turns it into the commit message that drives the release.

## Releases

Nothing to do by hand. On merge to `main`, [python-semantic-release](https://python-semantic-release.readthedocs.io/) reads the commits since the last tag, bumps the version, writes `CHANGELOG.md`, tags, and publishes a GitHub release with generated notes. Documentation is published per version at the same time.

If the release workflow reports that it is skipping, this repository has no release App configured yet; see the README.

## Updates from the template

This repository was generated from [coregraft](https://github.com/OO-LD/coregraft) and records the version it came from in `.copier-answers.yml`. A scheduled workflow opens a pull request when the template moves on, replaying template changes on top of your own. Review it like any other pull request, and search for `<<<<<<<` before merging: anything the merge could not resolve is left there deliberately, for a human to decide.
