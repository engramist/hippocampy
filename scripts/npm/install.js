#!/usr/bin/env node

const { spawnSync } = require('child_process');
const os = require('os');

console.log('Installing HippoCampy...');

if (os.platform() === 'win32') {
  console.error('Windows is not yet supported. Please use WSL.');
  process.exit(1);
}

const command = 'curl -fsSL https://raw.githubusercontent.com/djs54/hippocampy/main/scripts/install.sh | sh';
const result = spawnSync('sh', ['-c', command], { stdio: 'inherit' });

if (result.status !== 0) {
  console.error('Installation failed.');
  console.log('');
  console.log('Manual install: pip install hippocampy && campy setup');
  process.exit(result.status || 1);
}