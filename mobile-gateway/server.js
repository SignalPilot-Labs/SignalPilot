/**
 * SignalPilot Mobile Access Gateway
 *
 * Secure reverse proxy with session-based authentication.
 * Only exposes the web UI (3200) and monitor UI (3400).
 */

const express = require('express');
const helmet = require('helmet');
const cookieParser = require('cookie-parser');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const { createProxyMiddleware } = require('http-proxy-middleware');
const crypto = require('crypto');
const path = require('path');
const fs = require('fs');
const { authenticator } = require('otplib');
const QRCode = require('qrcode');

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
const PORT = parseInt(process.env.GATEWAY_PORT || '8080', 10);
const JWT_SECRET = process.env.JWT_SECRET || crypto.randomBytes(64).toString('hex');
const SESSION_MAX_AGE = parseInt(process.env.SESSION_MAX_AGE || '86400', 10); // 24h default
const WEB_UI_URL = process.env.WEB_UI_URL || 'http://host.docker.internal:3200';
const MONITOR_UI_URL = process.env.MONITOR_UI_URL || 'http://host.docker.internal:3400';
const GATEWAY_API_URL = process.env.GATEWAY_API_URL || 'http://host.docker.internal:3300';
const MONITOR_API_URL = process.env.MONITOR_API_URL || 'http://host.docker.internal:3401';
const MAX_LOGIN_ATTEMPTS = 5;
const LOCKOUT_DURATION = 15 * 60 * 1000; // 15 minutes
const CREDENTIALS_FILE = process.env.CREDENTIALS_FILE || path.join(__dirname, 'credentials.json');

// ---------------------------------------------------------------------------
// Credential store (file-based, bcrypt-hashed)
// ---------------------------------------------------------------------------
function loadCredentials() {
  if (!fs.existsSync(CREDENTIALS_FILE)) {
    return null;
  }
  return JSON.parse(fs.readFileSync(CREDENTIALS_FILE, 'utf-8'));
}

function saveCredentials(creds) {
  fs.writeFileSync(CREDENTIALS_FILE, JSON.stringify(creds, null, 2), { mode: 0o600 });
}

// ---------------------------------------------------------------------------
// Rate limiting / brute-force protection
// ---------------------------------------------------------------------------
const loginAttempts = new Map();

function checkRateLimit(ip) {
  const record = loginAttempts.get(ip);
  if (!record) return true;
  if (record.lockedUntil && Date.now() < record.lockedUntil) {
    return false;
  }
  if (record.lockedUntil && Date.now() >= record.lockedUntil) {
    loginAttempts.delete(ip);
    return true;
  }
  return record.attempts < MAX_LOGIN_ATTEMPTS;
}

function recordFailedAttempt(ip) {
  const record = loginAttempts.get(ip) || { attempts: 0 };
  record.attempts += 1;
  if (record.attempts >= MAX_LOGIN_ATTEMPTS) {
    record.lockedUntil = Date.now() + LOCKOUT_DURATION;
  }
  loginAttempts.set(ip, record);
}

function clearAttempts(ip) {
  loginAttempts.delete(ip);
}

// Periodic cleanup of stale entries
setInterval(() => {
  const now = Date.now();
  for (const [ip, record] of loginAttempts) {
    if (record.lockedUntil && now >= record.lockedUntil) {
      loginAttempts.delete(ip);
    }
  }
}, 60_000);

// ---------------------------------------------------------------------------
// Active sessions tracker (for revocation)
// ---------------------------------------------------------------------------
const activeSessions = new Map();

// ---------------------------------------------------------------------------
// Express app
// ---------------------------------------------------------------------------
const app = express();

// Trust proxy for X-Forwarded-For
app.set('trust proxy', 1);

// Security headers
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'", "'unsafe-inline'"],
      styleSrc: ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
      fontSrc: ["'self'", "https://fonts.gstatic.com"],
      imgSrc: ["'self'", "data:", "blob:"],
      connectSrc: ["'self'"],
      frameSrc: ["'self'"],
      frameAncestors: ["'none'"],
    },
  },
  crossOriginEmbedderPolicy: false,
}));

app.use(cookieParser());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ---------------------------------------------------------------------------
// Static files (login page, PWA manifest)
// ---------------------------------------------------------------------------
app.use('/public', express.static(path.join(__dirname, 'public')));

// ---------------------------------------------------------------------------
// Auth middleware
// ---------------------------------------------------------------------------
function verifyToken(req, res, next) {
  const token = req.cookies?.sp_session;
  if (!token) {
    return res.redirect('/login');
  }
  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    if (!activeSessions.has(decoded.sessionId)) {
      res.clearCookie('sp_session');
      return res.redirect('/login');
    }
    req.user = decoded;
    next();
  } catch {
    res.clearCookie('sp_session');
    return res.redirect('/login');
  }
}

function verifyTokenAPI(req, res, next) {
  const token = req.cookies?.sp_session;
  if (!token) {
    return res.status(401).json({ error: 'Not authenticated' });
  }
  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    if (!activeSessions.has(decoded.sessionId)) {
      return res.status(401).json({ error: 'Session revoked' });
    }
    req.user = decoded;
    next();
  } catch {
    return res.status(401).json({ error: 'Invalid session' });
  }
}

// ---------------------------------------------------------------------------
// Routes: Setup (first-time password creation)
// ---------------------------------------------------------------------------
app.get('/setup', (req, res) => {
  const creds = loadCredentials();
  if (creds) {
    return res.redirect('/login');
  }
  res.sendFile(path.join(__dirname, 'public', 'setup.html'));
});

app.post('/api/setup', async (req, res) => {
  const creds = loadCredentials();
  if (creds) {
    return res.status(400).json({ error: 'Already configured' });
  }

  const { username, password, enable_totp } = req.body;
  if (!username || !password) {
    return res.status(400).json({ error: 'Username and password required' });
  }
  if (password.length < 12) {
    return res.status(400).json({ error: 'Password must be at least 12 characters' });
  }

  const hash = await bcrypt.hash(password, 12);
  const newCreds = { username, passwordHash: hash, createdAt: new Date().toISOString() };

  if (enable_totp) {
    const secret = authenticator.generateSecret();
    newCreds.totpSecret = secret;
    newCreds.totpEnabled = true;
  }

  saveCredentials(newCreds);

  if (enable_totp) {
    const otpauth = authenticator.keyuri(username, 'SignalPilot', newCreds.totpSecret);
    const qrDataUrl = await QRCode.toDataURL(otpauth);
    return res.json({ success: true, totp: true, qr: qrDataUrl, secret: newCreds.totpSecret });
  }

  res.json({ success: true });
});

// ---------------------------------------------------------------------------
// Routes: Login
// ---------------------------------------------------------------------------
app.get('/login', (req, res) => {
  const creds = loadCredentials();
  if (!creds) {
    return res.redirect('/setup');
  }
  res.sendFile(path.join(__dirname, 'public', 'login.html'));
});

app.post('/api/login', async (req, res) => {
  const ip = req.ip;
  if (!checkRateLimit(ip)) {
    const record = loginAttempts.get(ip);
    const remaining = Math.ceil((record.lockedUntil - Date.now()) / 1000);
    return res.status(429).json({ error: `Too many attempts. Try again in ${remaining}s` });
  }

  const creds = loadCredentials();
  if (!creds) {
    return res.status(400).json({ error: 'Not configured' });
  }

  const { username, password, totp_code } = req.body;

  const validUser = username === creds.username;
  const validPass = validUser && await bcrypt.compare(password, creds.passwordHash);

  if (!validUser || !validPass) {
    recordFailedAttempt(ip);
    // Constant-time-ish response to avoid user enumeration
    return res.status(401).json({ error: 'Invalid credentials' });
  }

  // Check TOTP if enabled
  if (creds.totpEnabled) {
    if (!totp_code) {
      return res.json({ needs_totp: true });
    }
    const validTotp = authenticator.verify({ token: totp_code, secret: creds.totpSecret });
    if (!validTotp) {
      recordFailedAttempt(ip);
      return res.status(401).json({ error: 'Invalid 2FA code' });
    }
  }

  clearAttempts(ip);

  const sessionId = crypto.randomUUID();
  activeSessions.set(sessionId, {
    username: creds.username,
    createdAt: Date.now(),
    ip,
  });

  const token = jwt.sign(
    { username: creds.username, sessionId },
    JWT_SECRET,
    { expiresIn: SESSION_MAX_AGE }
  );

  res.cookie('sp_session', token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: SESSION_MAX_AGE * 1000,
    path: '/',
  });

  res.json({ success: true });
});

// ---------------------------------------------------------------------------
// Routes: Logout + Session management
// ---------------------------------------------------------------------------
app.post('/api/logout', verifyTokenAPI, (req, res) => {
  activeSessions.delete(req.user.sessionId);
  res.clearCookie('sp_session');
  res.json({ success: true });
});

app.get('/api/sessions', verifyTokenAPI, (req, res) => {
  const sessions = [];
  for (const [id, info] of activeSessions) {
    sessions.push({
      id: id.slice(0, 8) + '...',
      ip: info.ip,
      createdAt: new Date(info.createdAt).toISOString(),
      current: id === req.user.sessionId,
    });
  }
  res.json({ sessions });
});

app.post('/api/sessions/revoke-all', verifyTokenAPI, (req, res) => {
  const currentId = req.user.sessionId;
  for (const [id] of activeSessions) {
    if (id !== currentId) activeSessions.delete(id);
  }
  res.json({ success: true });
});

// ---------------------------------------------------------------------------
// Routes: PWA manifest
// ---------------------------------------------------------------------------
app.get('/manifest.json', (req, res) => {
  res.json({
    name: 'SignalPilot',
    short_name: 'SignalPilot',
    description: 'SignalPilot — Governed Database Intelligence',
    start_url: '/',
    display: 'standalone',
    background_color: '#0a0a1a',
    theme_color: '#6366f1',
    orientation: 'any',
    icons: [
      { src: '/public/icon-192.svg', sizes: '192x192', type: 'image/svg+xml' },
      { src: '/public/icon-512.svg', sizes: '512x512', type: 'image/svg+xml' },
    ],
  });
});

// ---------------------------------------------------------------------------
// Routes: Portal (authenticated landing page)
// ---------------------------------------------------------------------------
app.get('/', verifyToken, (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'portal.html'));
});

// ---------------------------------------------------------------------------
// Proxy: Web UI (/app/* → localhost:3200)
// ---------------------------------------------------------------------------
app.use('/app', verifyToken, createProxyMiddleware({
  target: WEB_UI_URL,
  changeOrigin: true,
  pathRewrite: { '^/app': '' },
  ws: true,
  on: {
    proxyReq: (proxyReq) => {
      proxyReq.setHeader('X-Forwarded-By', 'signalpilot-mobile-gateway');
    },
  },
}));

// ---------------------------------------------------------------------------
// Proxy: Gateway API (/gateway-api/* → localhost:3300)
// ---------------------------------------------------------------------------
app.use('/gateway-api', verifyTokenAPI, createProxyMiddleware({
  target: GATEWAY_API_URL,
  changeOrigin: true,
  pathRewrite: { '^/gateway-api': '' },
  on: {
    proxyReq: (proxyReq) => {
      proxyReq.setHeader('X-Forwarded-By', 'signalpilot-mobile-gateway');
    },
  },
}));

// ---------------------------------------------------------------------------
// Proxy: Monitor UI (/monitor/* → localhost:3400)
// ---------------------------------------------------------------------------
app.use('/monitor', verifyToken, createProxyMiddleware({
  target: MONITOR_UI_URL,
  changeOrigin: true,
  pathRewrite: { '^/monitor': '' },
  ws: true,
  on: {
    proxyReq: (proxyReq) => {
      proxyReq.setHeader('X-Forwarded-By', 'signalpilot-mobile-gateway');
    },
  },
}));

// ---------------------------------------------------------------------------
// Proxy: Monitor API (/monitor-api/* → localhost:3401)
// ---------------------------------------------------------------------------
app.use('/monitor-api', verifyTokenAPI, createProxyMiddleware({
  target: MONITOR_API_URL,
  changeOrigin: true,
  pathRewrite: { '^/monitor-api': '' },
  on: {
    proxyReq: (proxyReq) => {
      proxyReq.setHeader('X-Forwarded-By', 'signalpilot-mobile-gateway');
    },
  },
}));

// ---------------------------------------------------------------------------
// Session expiry cleanup
// ---------------------------------------------------------------------------
setInterval(() => {
  const now = Date.now();
  for (const [id, info] of activeSessions) {
    if (now - info.createdAt > SESSION_MAX_AGE * 1000) {
      activeSessions.delete(id);
    }
  }
}, 60_000);

// ---------------------------------------------------------------------------
// Start server
// ---------------------------------------------------------------------------
app.listen(PORT, '0.0.0.0', () => {
  const creds = loadCredentials();
  console.log('');
  console.log('  ╔══════════════════════════════════════════════╗');
  console.log('  ║     SignalPilot Mobile Access Gateway        ║');
  console.log('  ╠══════════════════════════════════════════════╣');
  console.log(`  ║  Port:     ${String(PORT).padEnd(33)}║`);
  console.log(`  ║  Web UI:   /app     → ${WEB_UI_URL.padEnd(21)}║`);
  console.log(`  ║  Monitor:  /monitor → ${MONITOR_UI_URL.padEnd(21)}║`);
  console.log(`  ║  Status:   ${creds ? 'Configured ✓' : 'SETUP REQUIRED → /setup'}${''.padEnd(creds ? 21 : 10)}║`);
  console.log('  ╚══════════════════════════════════════════════╝');
  console.log('');
  if (!creds) {
    console.log('  → Open http://localhost:' + PORT + '/setup to create your admin account');
  }
});
