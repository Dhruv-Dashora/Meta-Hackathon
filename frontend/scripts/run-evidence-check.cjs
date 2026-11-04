// Runner for the evidence-render regression check. Compiles the
// TypeScript check with the local tsc, marks the output dir CommonJS
// (the frontend package itself is ESM), then executes the assertions.
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const tsc = path.join(
  root,
  'node_modules',
  '.bin',
  process.platform === 'win32' ? 'tsc.cmd' : 'tsc',
);

const compiled = spawnSync(tsc, ['-p', 'tsconfig.check.json'], {
  cwd: root,
  stdio: 'inherit',
});
if (compiled.status !== 0) {
  process.exit(compiled.status ?? 1);
}

fs.writeFileSync(
  path.join(root, 'check-dist', 'package.json'),
  '{"type":"commonjs"}\n',
);

require('../check-dist/scripts/evidence-render-check.js');
