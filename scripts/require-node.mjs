#!/usr/bin/env node
/**
 * Fails fast if the active Node is too old for the toolchain.
 *
 * `engine-strict=true` in .npmrc only gates `npm install` — it does nothing for
 * `npm run dev`. This script closes that gap: wire it to a `predev` script and
 * the dev server refuses to start on the wrong Node rather than dying somewhere
 * deeper with a stack trace about ESM.
 *
 * Vite 7 requires Node 20.19+ or 22.12+ (it dropped Node 18, EOL April 2025).
 * This repo pins 22 via .nvmrc; the floor below is the real constraint.
 */

const MIN = { major: 20, minor: 19 };

const [major, minor] = process.versions.node.split('.').map(Number);
const tooOld = major < MIN.major || (major === MIN.major && minor < MIN.minor);

if (tooOld) {
  const want = `${MIN.major}.${MIN.minor}`;
  process.stderr.write(
    `\n  Node ${process.versions.node} is too old — this project needs >= ${want}.\n\n` +
      `  This machine keeps Node 18 as the global default for other projects,\n` +
      `  so switch per-project instead of changing the default:\n\n` +
      `      nvm use            # reads .nvmrc in the repo root (pins 22)\n\n` +
      `  To make that automatic on cd, add nvm's shell hook:\n` +
      `      https://github.com/nvm-sh/nvm#deeper-shell-integration\n\n`,
  );
  process.exit(1);
}
