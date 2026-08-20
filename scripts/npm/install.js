#!/usr/bin/env node

const os = require('os');

if (os.platform() === 'win32') {
  console.error('Windows is not yet supported. Please use WSL.');
  process.exit(1);
}

console.log('HippoCampy install is intentionally opt-in and does not execute remote code automatically.');
console.log('');
console.log('Safe install flow:');
console.log('  1) pip install hippocampy');
console.log('  2) campy setup');
console.log('');
console.log('If you want to run the repo installer explicitly from a checked-out copy:');
console.log('  bash scripts/install.sh');
process.exit(0);
