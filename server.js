const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { runTurn, cancelTurn } = require('./lib/agy-manager');
const { listConversations, getConversation, deleteConversation } = require('./lib/db-reader');
const { getModels } = require('./lib/models');

const PORT = parseInt(process.env.PORT || '4567', 10);
const PUBLIC_DIR = path.join(__dirname, 'public');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon'
};

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => {
      body += chunk;
      if (body.length > 50 * 1024 * 1024) {
        req.destroy();
        reject(new Error('Payload too large'));
      }
    });
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (err) {
        reject(err);
      }
    });
  });
}

function sendJson(res, statusCode, data) {
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type'
  });
  res.end(JSON.stringify(data));
}

function serveStatic(req, res, pathname) {
  let filePath = path.join(PUBLIC_DIR, pathname === '/' ? 'index.html' : pathname);
  
  // Security check: prevent directory traversal
  if (!filePath.startsWith(PUBLIC_DIR)) {
    res.writeHead(403);
    return res.end('Forbidden');
  }

  fs.stat(filePath, (err, stats) => {
    if (err || !stats.isFile()) {
      // SPA Fallback: serve index.html
      filePath = path.join(PUBLIC_DIR, 'index.html');
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME_TYPES[ext] || 'application/octet-stream';

    fs.readFile(filePath, (readErr, content) => {
      if (readErr) {
        res.writeHead(500);
        return res.end('Server Error');
      }
      res.writeHead(200, {
        'Content-Type': contentType,
        'Cache-Control': 'no-cache'
      });
      res.end(content);
    });
  });
}

const server = http.createServer(async (req, res) => {
  const urlObj = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = urlObj.pathname;

  // Handle CORS Preflight
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type'
    });
    return res.end();
  }

  // Healthcheck
  if (pathname === '/health') {
    return sendJson(res, 200, { status: 'ok', uptime: process.uptime() });
  }

  // API Routes
  if (pathname === '/api/config' && req.method === 'GET') {
    return sendJson(res, 200, {
      user: os.userInfo().username,
      home: os.homedir(),
      defaultWorkspace: process.env.HOME || '/home/manojb',
      defaultModel: 'gemini-3.8-flash-high'
    });
  }

  if (pathname === '/api/models' && req.method === 'GET') {
    const models = await getModels();
    return sendJson(res, 200, { models });
  }

  if (pathname === '/api/conversations' && req.method === 'GET') {
    const list = listConversations();
    return sendJson(res, 200, { conversations: list });
  }

  const convMatch = pathname.match(/^\/api\/conversations\/([a-zA-Z0-9_-]+)$/);
  if (convMatch && req.method === 'GET') {
    const convId = convMatch[1];
    const data = getConversation(convId);
    return sendJson(res, 200, data);
  }

  if (convMatch && req.method === 'DELETE') {
    const convId = convMatch[1];
    const success = deleteConversation(convId);
    return sendJson(res, 200, { success });
  }

  if (pathname === '/api/cancel' && req.method === 'POST') {
    try {
      const { conversationId } = await parseBody(req);
      const cancelled = cancelTurn(conversationId);
      return sendJson(res, 200, { cancelled });
    } catch (err) {
      return sendJson(res, 400, { error: err.message });
    }
  }

  // Chat Streaming Endpoint (Server-Sent Events)
  if (pathname === '/api/chat' && req.method === 'POST') {
    let body;
    try {
      body = await parseBody(req);
    } catch (err) {
      return sendJson(res, 400, { error: 'Invalid JSON body' });
    }

    const {
      prompt,
      conversationId,
      model,
      skipPermissions = true,
      sandbox = false,
      mode = null,
      cwd
    } = body;

    if (!prompt || typeof prompt !== 'string' || !prompt.trim()) {
      return sendJson(res, 400, { error: 'Prompt is required' });
    }

    // Set up SSE headers
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'Access-Control-Allow-Origin': '*'
    });

    const sendSse = (data) => {
      res.write(`data: ${JSON.stringify(data)}\n\n`);
    };

    const turn = runTurn({
      prompt: prompt.trim(),
      conversationId: conversationId || null,
      model: model || null,
      skipPermissions: Boolean(skipPermissions),
      sandbox: Boolean(sandbox),
      mode: mode || null,
      cwd: cwd || os.homedir()
    });

    turn.on('event', (evt) => {
      sendSse(evt);
      if (evt.type === 'result' || evt.type === 'done') {
        res.end();
      }
    });

    // Handle client disconnect: cancel the process
    req.on('close', () => {
      turn.cancel();
    });

    return;
  }

  // Serve Static Frontend Assets
  serveStatic(req, res, pathname);
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[Antigravity GUI] Server running at http://127.0.0.1:${PORT}`);
});

process.on('SIGTERM', () => {
  console.log('Shutting down server...');
  server.close(() => process.exit(0));
});
