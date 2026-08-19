#!/usr/bin/env node

const crypto = require('crypto');
const fs = require('fs');
const https = require('https');
const path = require('path');
const { spawnSync } = require('child_process');
const os = require('os');

const packageJson = require('./package.json');

const INSTALL_REF = `v${packageJson.version}`;
const INSTALL_URL = `https://raw.githubusercontent.com/engramist/hippocampy/${INSTALL_REF}/scripts/install.sh`;
const INSTALL_SHA256 = '81b0f975f4cacb4002cf5261624822ef92df11e76f0cfb69fc3138d6e397e3a5';

function downloadScript(url) {
  return new Promise((resolve, reject) => {
    https
      .get(url, (response) => {
        if (response.statusCode !== 200) {
          reject(new Error(`Failed to download installer: HTTP ${response.statusCode}`));
          response.resume();
          return;
        }

        const chunks = [];
        response.on('data', (chunk) => chunks.push(chunk));
        response.on('end', () => resolve(Buffer.concat(chunks)));
      })
      .on('error', (error) => reject(error));
  });
}

function sha256Hex(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

console.log('Installing HippoCampy...');

if (os.platform() === 'win32') {
  console.error('Windows is not yet supported. Please use WSL.');
  process.exit(1);
}

async function main() {
  try {
    const scriptContent = await downloadScript(INSTALL_URL);
    const observedHash = sha256Hex(scriptContent);
    if (observedHash !== INSTALL_SHA256) {
      console.error('Installation aborted: installer checksum mismatch.');
      console.error(`Expected: ${INSTALL_SHA256}`);
      console.error(`Observed: ${observedHash}`);
      console.error('Refusing to execute unverified remote code.');
      process.exit(1);
    }

    const tempPath = path.join(
      os.tmpdir(),
      `hippocampy-install-${Date.now()}-${process.pid}.sh`
    );
    fs.writeFileSync(tempPath, scriptContent, { mode: 0o700 });
    const result = spawnSync('sh', [tempPath], { stdio: 'inherit' });
    fs.unlinkSync(tempPath);

    if (result.status !== 0) {
      console.error('Installation failed.');
      console.log('');
      console.log('Manual install: pip install hippocampy && campy setup');
      process.exit(result.status || 1);
    }
  } catch (error) {
    console.error(`Installation failed: ${error.message}`);
    console.log('');
    console.log('Manual install: pip install hippocampy && campy setup');
    process.exit(1);
  }
}

main();