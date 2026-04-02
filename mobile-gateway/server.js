/**
 * SignalPilot Mobile Access Gateway
 *
 * Secure reverse proxy with:
 *  - Session-based JWT authentication (httpOnly, secure cookies)
 *  - Optional TOTP 2FA
 *  - CSRF protection on state-changing requests
 *  - Brute-force lockout (per-IP)
 *  - Cloudflare Tunnel support for secure remote access
 *  - PWA with service worker for mobile app-like experience
 *  - Minimum-exposure proxy: only Web UI (3200) and Monitor UI (3400)
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
const SESSION_MAX_AGE = parseInt(process.env.SESSION_MAX_AGE || '86400', 10); // 24h
const WEB_UI_URL = process.env.WEB_UI_URL || 'http://host.docker.internal:3200';
const MONITOR_UI_URL = process.env.MONITOR_UI_URL || 'http://host.docker.internal:3400';
const GATEWAY_API_URL = process.env.GATEWAY_API_URL || 'http://host.docker.internal:3300';
const MONITOR_API_URL = process.env.MONITOR_API_URL || 'http://host.docker.internal:3401';
const MAX_LOGIN_ATTEMPTS = 5;
const LOCKOUT_DURATION = 15 * 60 * 1000; // 15 minutes
const CREDENTIALS_FILE = process.env.CREDENTIALS_FILE || path.join(__dirname, 'credentials.json');
const TUNNEL_DOMAIN = process.env.TUNNEL_DOMAIN || ''; // e.g. signalpilot.example.com

// ---------------------------------------------------------------------------
// Credential store (file-based, bcrypt-hashed)
// ---------------------------------------------------------------------------
function loadCredentials() {
  if (!fs.existsSync(CREDENTIALS_FILE)) return null;
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
  if (record.lockedUntil && Date.now() < record.lockedUntil) return false;
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

// Periodic cleanup
setInterval(() => {
  const now = Date.now();
  for (const [ip, record] of loginAttempts) {
    if (record.lockedUntil && now >= record.lockedUntil) loginAttempts.delete(ip);
  }
}, 60_000);

// ---------------------------------------------------------------------------
// Active sessions tracker
// ---------------------------------------------------------------------------
const activeSessions = new Map();

// Session expiry cleanup
setInterval(() => {
  const now = Date.now();
  for (const [id, info] of activeSessions) {
    if (now - info.createdAt > SESSION_MAX_AGE * 1000) activeSessions.delete(id);
  }
}, 60_000);

// ---------------------------------------------------------------------------
// CSRF token generation & validation
// ---------------------------------------------------------------------------
function generateCsrfToken(sessionId) {
  return crypto.createHmac('sha256', JWT_SECRET).update(sessionId).digest('hex').slice(0, 32);
}

function validateCsrf(req, res, next) {
  if (['GET', 'HEAD', 'OPTIONS'].includes(req.method)) return next();
  const token = req.headers['x-csrf-token'] || req.body?._csrf;
  const sessionToken = req.cookies?.sp_session;
  if (!sessionToken) return res.status(403).json({ error: 'No session' });
  try {
    const decoded = jwt.verify(sessionToken, JWT_SECRET);
    const expected = generateCsrfToken(decoded.sessionId);
    if (!token || !crypto.timingSafeEqual(Buffer.from(token), Buffer.from(expected))) {
      return res.status(403).json({ error: 'Invalid CSRF token' });
    }
    next();
  } catch {
    return res.status(403).json({ error: 'Invalid session' });
  }
}

// ---------------------------------------------------------------------------
// Express app
// ---------------------------------------------------------------------------
const app = express();

app.set('trust proxy', 1);

// Determine allowed connect-src for CSP
const connectSources = ["'self'"];
if (TUNNEL_DOMAIN) connectSources.push(`https://${TUNNEL_DOMAIN}`);

app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'", "'unsafe-inline'"],
      styleSrc: ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
      fontSrc: ["'self'", "https://fonts.gstatic.com"],
      imgSrc: ["'self'", "data:", "blob:"],
      connectSrc: connectSources,
      frameSrc: ["'self'"],
      frameAncestors: ["'none'"],
      workerSrc: ["'self'"],
    },
  },
  crossOriginEmbedderPolicy: false,
  referrerPolicy: { policy: 'strict-origin-when-cross-origin' },
}));

app.use(cookieParser());
app.use(express.json({ limit: '1mb' }));
app.use(express.urlencoded({ extended: true, limit: '1mb' }));

// ---------------------------------------------------------------------------
// Static files
// ---------------------------------------------------------------------------
app.use('/public', express.static(path.join(__dirname, 'public'), {
  maxAge: '7d',
  immutable: true,
}));

// Service worker (must be served from root scope)
app.get('/sw.js', (req, res) => {
  res.setHeader('Content-Type', 'application/javascript');
  res.setHeader('Cache-Control', 'no-cache');
  res.sendFile(path.join(__dirname, 'public', 'sw.js'));
});

// ---------------------------------------------------------------------------
// Auth middleware
// ---------------------------------------------------------------------------
function verifyToken(req, res, next) {
  const token = req.cookies?.sp_session;
  if (!token) return res.redirect('/login');
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
  if (!token) return res.status(401).json({ error: 'Not authenticated' });
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
// Routes: Setup (first-time account creation)
// ---------------------------------------------------------------------------
app.get('/setup', (req, res) => {
  if (loadCredentials()) return res.redirect('/login');
  res.sendFile(path.join(__dirname, 'public', 'setup.html'));
});

app.post('/api/setup', async (req, res) => {
  if (loadCredentials()) return res.status(400).json({ error: 'Already configured' });

  const { username, password, enable_totp } = req.body;
  if (!username || !password) return res.status(400).json({ error: 'Username and password required' });
  if (password.length < 12) return res.status(400).json({ error: 'Password must be at least 12 characters' });
  if (username.length > 64) return res.status(400).json({ error: 'Username too long' });

  const hash = await bcrypt.hash(password, 12);
  const newCreds = { username: username.trim(), passwordHash: hash, createdAt: new Date().toISOString() };

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
  if (!loadCredentials()) return res.redirect('/setup');
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
  if (!creds) return res.status(400).json({ error: 'Not configured' });

  const { username, password, totp_code } = req.body;
  const validUser = username === creds.username;
  const validPass = validUser && await bcrypt.compare(password, creds.passwordHash);

  if (!validUser || !validPass) {
    recordFailedAttempt(ip);
    return res.status(401).json({ error: 'Invalid credentials' });
  }

  if (creds.totpEnabled) {
    if (!totp_code) return res.json({ needs_totp: true });
    const validTotp = authenticator.verify({ token: totp_code, secret: creds.totpSecret });
    if (!validTotp) {
      recordFailedAttempt(ip);
      return res.status(401).json({ error: 'Invalid 2FA code' });
    }
  }

  clearAttempts(ip);

  const sessionId = crypto.randomUUID();
  const userAgent = req.headers['user-agent'] || 'unknown';
  activeSessions.set(sessionId, {
    username: creds.username,
    createdAt: Date.now(),
    ip,
    userAgent: userAgent.slice(0, 200),
  });

  const token = jwt.sign(
    { username: creds.username, sessionId },
    JWT_SECRET,
    { expiresIn: SESSION_MAX_AGE }
  );

  res.cookie('sp_session', token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production' || !!TUNNEL_DOMAIN,
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
      userAgent: info.userAgent,
      createdAt: new Date(info.createdAt).toISOString(),
      current: id === req.user.sessionId,
    });
  }
  res.json({ sessions });
});

app.post('/api/sessions/revoke-all', verifyTokenAPI, validateCsrf, (req, res) => {
  const currentId = req.user.sessionId;
  for (const [id] of activeSessions) {
    if (id !== currentId) activeSessions.delete(id);
  }
  res.json({ success: true });
});

// CSRF token endpoint
app.get('/api/csrf-token', verifyTokenAPI, (req, res) => {
  res.json({ token: generateCsrfToken(req.user.sessionId) });
});

// ---------------------------------------------------------------------------
// Routes: Health (for tunnel health checks)
// ---------------------------------------------------------------------------
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// ---------------------------------------------------------------------------
// Routes: PWA manifest
// ---------------------------------------------------------------------------
app.get('/manifest.json', (req, res) => {
  res.json({
    name: 'SignalPilot Mobile',
    short_name: 'SignalPilot',
    description: 'SignalPilot — Governed Database Intelligence',
    start_url: '/',
    display: 'standalone',
    background_color: '#0a0a1a',
    theme_color: '#6366f1',
    orientation: 'any',
    categories: ['developer', 'productivity'],
    icons: [
      { src: '/public/icon-192.svg', sizes: '192x192', type: 'image/svg+xml', purpose: 'any' },
      { src: '/public/icon-512.svg', sizes: '512x512', type: 'image/svg+xml', purpose: 'any maskable' },
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
// Proxy: Web UI (/app/* -> localhost:3200)
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
// Proxy: Gateway API (/gateway-api/* -> localhost:3300)
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
// Proxy: Monitor UI (/monitor/* -> localhost:3400)
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
// Proxy: Monitor API (/monitor-api/* -> localhost:3401)
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
// Catch-all: 404
// ---------------------------------------------------------------------------
app.use((req, res) => {
  res.status(404).json({ error: 'Not found' });
});

// ---------------------------------------------------------------------------
// Start server
// ---------------------------------------------------------------------------
app.listen(PORT, '0.0.0.0', () => {
  const creds = loadCredentials();
  console.log('');
  console.log('  +================================================+');
  console.log('  |     SignalPilot Mobile Access Gateway            |');
  console.log('  +================================================+');
  console.log(`  |  Port:     ${String(PORT).padEnd(35)}|`);
  console.log(`  |  Web UI:   /app     -> ${WEB_UI_URL.padEnd(22)}|`);
  console.log(`  |  Monitor:  /monitor -> ${MONITOR_UI_URL.padEnd(22)}|`);
  if (TUNNEL_DOMAIN) {
    console.log(`  |  Tunnel:   https://${TUNNEL_DOMAIN.padEnd(26)}|`);
  }
  console.log(`  |  Status:   ${creds ? 'Configured' : 'SETUP REQUIRED -> /setup'}${''.padEnd(creds ? 25 : 12)}|`);
  console.log('  +================================================+');
  console.log('');
  if (!creds) {
    console.log('  -> Open http://localhost:' + PORT + '/setup to create your admin account');
    console.log('');
  }
  if (TUNNEL_DOMAIN) {
    console.log('  Remote access via Cloudflare Tunnel:');
    console.log(`  -> https://${TUNNEL_DOMAIN}`);
    console.log('');
  }
});
