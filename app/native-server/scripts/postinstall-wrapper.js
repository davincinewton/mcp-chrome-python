#!/usr/bin/env node
/**
 * Postinstall wrapper that handles both built and unbuilt states.
 * - If dist/scripts/postinstall.js exists, run it directly.
 * - Otherwise, try to run the TypeScript source via ts-node.
 * - If neither works, exit gracefully (0) so pnpm install doesn't fail.
 */
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const distScript = path.join(__dirname, '..', 'dist', 'scripts', 'postinstall.js');
const srcScript = path.join(__dirname, '..', 'src', 'scripts', 'postinstall.ts');

// Case 1: Built version exists — run it directly
if (fs.existsSync(distScript)) {
  execSync(`node "${distScript}"`, { stdio: 'inherit' });
  process.exit(0);
}

// Case 2: Source exists but not built — try ts-node
if (fs.existsSync(srcScript)) {
  try {
    console.log('postinstall: dist not built, attempting via ts-node...');
    execSync(`npx ts-node "${srcScript}"`, { stdio: 'inherit' });
    process.exit(0);
  } catch (err) {
    console.warn('postinstall: ts-node failed, skipping registration.');
    console.warn('  Build the native-server first: cd app/native-server && pnpm run build');
    process.exit(0);
  }
}

// Case 3: Neither exists — skip gracefully
console.log('postinstall: skipped (neither dist nor src found)');
process.exit(0);
