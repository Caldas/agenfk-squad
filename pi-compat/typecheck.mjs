// Optional, offline strict checking. Never install dependencies or alter tsconfig files.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const require = createRequire(import.meta.url);
let temporary;
try {
  if (!process.env.PI_COMPAT_PI_ROOT) throw new Error('Set PI_COMPAT_PI_ROOT to the installed Pi package directory.');
  const root = fs.realpathSync(process.env.PI_COMPAT_PI_ROOT);
  if (JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).name !== '@earendil-works/pi-coding-agent') throw new Error('PI_COMPAT_PI_ROOT is not the Pi package directory.');
  const compiler = process.env.PI_COMPAT_TSC || require.resolve('typescript/lib/tsc.js', { paths: [root, process.cwd(), path.join(os.homedir(), '.pi/agent/claude-compat/tools')] });
  const directory = path.dirname(fileURLToPath(import.meta.url));
  temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'squad-pi-types-'));
  const config = path.join(temporary, 'tsconfig.json');
  fs.writeFileSync(config, JSON.stringify({ compilerOptions: {
    target: 'ES2022', module: 'ESNext', moduleResolution: 'Bundler', allowImportingTsExtensions: true,
    noEmit: true, strict: true, skipLibCheck: true, baseUrl: root,
    typeRoots: [path.join(root, 'node_modules/@types')],
    paths: {
      '@earendil-works/pi-coding-agent': ['dist/index.d.ts'],
      '@earendil-works/pi-ai': ['node_modules/@earendil-works/pi-ai/dist/index.d.ts'],
      typebox: ['node_modules/typebox/build/index.d.mts'],
      '@earendil-works/pi-tui': ['node_modules/@earendil-works/pi-tui/dist/index.d.ts'],
    },
  }, include: [path.join(directory, '*.ts')] }));
  const result = spawnSync(process.execPath, [compiler, '-p', config], { stdio: 'inherit' });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
} catch (error) {
  console.error('Pi typecheck:', error.message);
  console.error('Requires an installed Pi runtime and TypeScript; PI_COMPAT_TSC may select the compiler JS entry point.');
  process.exitCode = 1;
} finally {
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
}
