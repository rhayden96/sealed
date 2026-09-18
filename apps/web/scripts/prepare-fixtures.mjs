import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = resolve(app, '../../fixtures/seals');
const destination = join(app, 'public/replay/seals');
await mkdir(destination, { recursive: true });
const seals = [];
for (const filename of (await readdir(source)).filter((name) => name.endsWith('.json')).sort()) {
  const seal = JSON.parse(await readFile(join(source, filename), 'utf8'));
  if (!/^[A-Za-z0-9_-]+$/.test(seal.id)) throw new Error('Invalid fixture identifier');
  seals.push(seal);
  await writeFile(join(destination, `${seal.id}.json`), JSON.stringify(seal, null, 2) + '\n');
}
await writeFile(join(destination, 'index.json'), JSON.stringify({ seals }, null, 2) + '\n');
