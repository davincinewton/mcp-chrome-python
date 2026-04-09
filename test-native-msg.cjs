#!/usr/bin/env node
/**
 * Test script to verify Chrome Native Messaging is working
 * Run this from command line with node
 */

const fs = require('fs');
const path = require('path');

const manifestPath = path.join(process.env.HOME, '.config/google-chrome/NativeMessagingHosts/com.chromemcp.nativehost.json');

console.log('=== Chrome Native Messaging Test ===');
console.log('Manifest path:', manifestPath);
console.log('HOME:', process.env.HOME);

try {
  const content = fs.readFileSync(manifestPath, 'utf8');
  console.log('Manifest exists: YES');
  console.log('Manifest content:');
  console.log(content);

  const manifest = JSON.parse(content);
  console.log('\nParsed manifest:');
  console.log('  name:', manifest.name);
  console.log('  path:', manifest.path);
  console.log('  type:', manifest.type);

  // Check if the binary exists
  const binaryPath = manifest.path;
  if (fs.existsSync(binaryPath)) {
    console.log('Binary exists: YES');
    const stats = fs.statSync(binaryPath);
    console.log('Binary permissions:', stats.mode.toString(8));
  } else {
    console.log('Binary exists: NO -', binaryPath);
  }
} catch (err) {
  console.error('ERROR:', err.message);
}
