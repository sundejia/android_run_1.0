import path from 'node:path'

/**
 * Git paths are like `android_run_test-main/wecom-desktop/...` (one segment after repo root).
 * Absolute paths may include the nested folder twice on disk. Use glob patterns with a leading ** segment so both match.
 * cwd for commands = this directory (nested `android_run_test-main`).
 */
const REPO_SUBDIR = 'android_run_test-main/'

function toProjectRelative(gitPath) {
  const norm = gitPath.replace(/\\/g, '/')
  if (path.isAbsolute(gitPath)) {
    return path.relative(process.cwd(), path.normalize(gitPath))
  }
  if (norm.startsWith(REPO_SUBDIR)) {
    return norm.slice(REPO_SUBDIR.length).replace(/\//g, path.sep)
  }
  return path.join('..', gitPath)
}

function joinPaths(files) {
  return files.map(toProjectRelative).join(' ')
}

// We deliberately invoke ruff via the system `python -m ruff` rather than
// `uv run --extra dev`. uv would otherwise try to rebuild every binary
// dep of the project (notably `pilk`) every time a Python file is
// committed, which fails on Windows hosts without MSVC build tools. The
// system `ruff` package is installed alongside `pip install -e .[dev]`.
const ruff = (files) => {
  if (!files.length) return []
  const paths = joinPaths(files)
  return [
    'python -m ruff check --fix ' + paths,
    'python -m ruff format ' + paths,
  ]
}

const prettierWrite = (files) => {
  if (!files.length) return []
  return 'npx prettier --write --config wecom-desktop/.prettierrc ' + joinPaths(files)
}

/** @type {import('lint-staged').Configuration} */
export default {
  '**/wecom-desktop/src/**/*.{ts,tsx,vue,js}': (files) => {
    if (!files.length) return []
    const paths = joinPaths(files)
    return [
      'npx eslint --fix --config wecom-desktop/.eslintrc.cjs ' + paths,
      'npx prettier --write --config wecom-desktop/.prettierrc ' + paths,
    ]
  },
  '**/wecom-desktop/src/**/*.{json,css}': prettierWrite,
  '**/android_run_test-main/src/**/*.py': ruff,
  '**/tests/**/*.py': ruff,
  '**/wecom-desktop/backend/**/*.py': ruff,
  '**/docs/**/*.md': prettierWrite,
  '**/daily-operations-monitoring-plan.md': prettierWrite,
  'daily-operations-monitoring-plan.md': prettierWrite,
  '../daily-operations-monitoring-plan.md': prettierWrite,
}
