#!/usr/bin/env node
/**
 * Utility to hash a password for manual credential setup.
 * Usage: node scripts/hash-password.js <password>
 */
const bcrypt = require('bcryptjs');

const password = process.argv[2];
if (!password) {
  console.error('Usage: node scripts/hash-password.js <password>');
  process.exit(1);
}

bcrypt.hash(password, 12).then(hash => {
  console.log('Hash:', hash);
  console.log('\nTo create credentials.json manually:');
  console.log(JSON.stringify({
    username: 'admin',
    passwordHash: hash,
    createdAt: new Date().toISOString(),
  }, null, 2));
});
