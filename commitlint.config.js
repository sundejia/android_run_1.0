export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // Type must be one of the following
    'type-enum': [
      2,
      'always',
      [
        'feat',     // New feature
        'fix',      // Bug fix
        'docs',     // Documentation only
        'style',    // Code style (formatting, no logic change)
        'refactor', // Code refactoring (no feature/fix)
        'perf',     // Performance improvement
        'test',     // Adding tests
        'chore',    // Maintenance tasks
        'ci',       // CI/CD changes
        'build',    // Build system changes
        'revert',   // Revert previous commit
      ],
    ],
    // Type must be lowercase
    'type-case': [2, 'always', 'lower-case'],
    // Subject must not be empty
    'subject-empty': [2, 'never'],
    // Subject must not end with period
    'subject-full-stop': [2, 'never', '.'],
    // Header max length
    'header-max-length': [2, 'always', 100],
    // Body max line length (relaxed for URLs)
    'body-max-line-length': [1, 'always', 200],
  },
  // Help message for invalid commits
  helpUrl: 'https://www.conventionalcommits.org/',
}
