import js from '../../apps/web/node_modules/@eslint/js/src/index.js';
import globals from '../../apps/web/node_modules/globals/index.js';

export default [
  { ignores: ['node_modules/**'] },
  {
    files: ['**/*.{js,mjs}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      ...js.configs.recommended.rules,
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
];
