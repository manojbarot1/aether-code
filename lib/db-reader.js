const fs = require('fs');
const path = require('path');
const os = require('os');

const HOME_DIR = os.homedir();
const CLI_DIR = path.join(HOME_DIR, '.gemini', 'antigravity-cli');
const SUMMARIES_DB = path.join(CLI_DIR, 'conversation_summaries.db');
const BRAIN_DIR = path.join(CLI_DIR, 'brain');

let DatabaseSync = null;
try {
  ({ DatabaseSync } = require('node:sqlite'));
} catch (e) {
  DatabaseSync = null;
}

function extractFirstUserPrompt(conversationId) {
  const fullPath = path.join(BRAIN_DIR, conversationId, '.system_generated', 'logs', 'transcript_full.jsonl');
  const compactPath = path.join(BRAIN_DIR, conversationId, '.system_generated', 'logs', 'transcript.jsonl');
  const targetPath = fs.existsSync(fullPath) ? fullPath : (fs.existsSync(compactPath) ? compactPath : null);
  if (!targetPath) return null;

  try {
    const raw = fs.readFileSync(targetPath, 'utf8');
    const lines = raw.split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const item = JSON.parse(line);
        if (item.type === 'USER_INPUT' && item.content) {
          let text = item.content;
          const match = text.match(/<USER_REQUEST>([\s\S]*?)<\/USER_REQUEST>/);
          if (match) {
            text = match[1];
          } else {
            text = text.replace(/<ADDITIONAL_METADATA>[\s\S]*?<\/ADDITIONAL_METADATA>/g, '')
                       .replace(/<USER_SETTINGS_CHANGE>[\s\S]*?<\/USER_SETTINGS_CHANGE>/g, '');
          }
          const clean = text.replace(/\s+/g, ' ').trim();
          if (clean) {
            return clean.length > 55 ? clean.slice(0, 52) + '...' : clean;
          }
        }
      } catch (e) {}
    }
  } catch (e) {}
  return null;
}

function listConversations() {
  const conversationsMap = new Map();

  // 1. Try reading from conversation_summaries.db
  if (DatabaseSync && fs.existsSync(SUMMARIES_DB)) {
    try {
      const db = new DatabaseSync(SUMMARIES_DB, { readOnly: true });
      const rows = db.prepare(`
        SELECT conversation_id, title, preview, last_modified_time
        FROM conversation_summaries
        ORDER BY last_modified_time DESC
      `).all();
      db.close();

      for (const row of rows) {
        let title = (row.title || '').trim();
        let preview = (row.preview || '').trim();

        if (!title || title.startsWith('Session ') || title.toLowerCase() === 'untitled conversation') {
          const fromPrompt = extractFirstUserPrompt(row.conversation_id);
          if (fromPrompt) {
            title = fromPrompt;
            if (!preview) preview = fromPrompt;
          }
        }

        conversationsMap.set(row.conversation_id, {
          id: row.conversation_id,
          title: title || preview || 'Conversation',
          preview: preview || title || '',
          lastModified: row.last_modified_time || new Date().toISOString()
        });
      }
    } catch (err) {
      console.error('Error reading conversation_summaries.db:', err.message);
    }
  }

  // 2. Scan brain directory to capture recent sessions not yet committed to DB
  if (fs.existsSync(BRAIN_DIR)) {
    try {
      const entries = fs.readdirSync(BRAIN_DIR, { withFileTypes: true });
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        const transcriptPath = path.join(BRAIN_DIR, entry.name, '.system_generated', 'logs', 'transcript.jsonl');
        const fullTranscriptPath = path.join(BRAIN_DIR, entry.name, '.system_generated', 'logs', 'transcript_full.jsonl');
        const targetPath = fs.existsSync(fullTranscriptPath) ? fullTranscriptPath : (fs.existsSync(transcriptPath) ? transcriptPath : null);

        if (targetPath) {
          const existing = conversationsMap.get(entry.name);
          const stats = fs.statSync(targetPath);
          const fromPrompt = extractFirstUserPrompt(entry.name);

          if (!existing) {
            conversationsMap.set(entry.name, {
              id: entry.name,
              title: fromPrompt || 'Conversation',
              preview: fromPrompt || '',
              lastModified: stats.mtime.toISOString()
            });
          } else if (!existing.title || existing.title.startsWith('Session ') || existing.title.toLowerCase() === 'untitled conversation') {
            if (fromPrompt) {
              existing.title = fromPrompt;
              if (!existing.preview) existing.preview = fromPrompt;
            }
          }
        }
      }
    } catch (err) {
      console.error('Error scanning brain dir:', err.message);
    }
  }

  const list = Array.from(conversationsMap.values());
  list.sort((a, b) => new Date(b.lastModified) - new Date(a.lastModified));
  return list;
}

function getConversation(conversationId) {
  const transcriptPath = path.join(BRAIN_DIR, conversationId, '.system_generated', 'logs', 'transcript.jsonl');
  if (!fs.existsSync(transcriptPath)) {
    return { id: conversationId, messages: [] };
  }

  try {
    const raw = fs.readFileSync(transcriptPath, 'utf8');
    const lines = raw.trim().split('\n');
    const messages = [];

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const item = JSON.parse(line);

        if (item.type === 'USER_INPUT') {
          let text = item.content || '';
          const match = text.match(/<USER_REQUEST>([\s\S]*?)<\/USER_REQUEST>/);
          if (match) {
            text = match[1].trim();
          } else {
            // Strip any remaining metadata tags
            text = text.replace(/<ADDITIONAL_METADATA>[\s\S]*?<\/ADDITIONAL_METADATA>/g, '')
                       .replace(/<USER_SETTINGS_CHANGE>[\s\S]*?<\/USER_SETTINGS_CHANGE>/g, '')
                       .trim();
          }
          if (text) {
            messages.push({
              role: 'user',
              content: text,
              timestamp: item.created_at || new Date().toISOString()
            });
          }
        } else if (item.type === 'PLANNER_RESPONSE' && item.source === 'MODEL') {
          const content = item.content || '';
          const thinking = item.thinking || '';
          const toolCalls = item.tool_calls || [];
          messages.push({
            role: 'assistant',
            content,
            thinking,
            toolCalls,
            timestamp: item.created_at || new Date().toISOString()
          });
        }
      } catch (parseErr) {
        // Skip malformed line
      }
    }

    return { id: conversationId, messages };
  } catch (err) {
    console.error(`Error reading transcript for ${conversationId}:`, err);
    return { id: conversationId, messages: [] };
  }
}

function deleteConversation(conversationId) {
  if (DatabaseSync && fs.existsSync(SUMMARIES_DB)) {
    try {
      const db = new DatabaseSync(SUMMARIES_DB);
      db.prepare(`DELETE FROM conversation_summaries WHERE conversation_id = ?`).run(conversationId);
      db.close();
      return true;
    } catch (e) {
      console.error('Error deleting from db:', e.message);
    }
  }
  return false;
}

function getSessionMemory(conversationId) {
  const convDir = path.join(BRAIN_DIR, conversationId);
  const memoryFile = path.join(convDir, 'memory.json');
  const fullTranscriptPath = path.join(convDir, '.system_generated', 'logs', 'transcript_full.jsonl');
  const compactTranscriptPath = path.join(convDir, '.system_generated', 'logs', 'transcript.jsonl');
  const targetPath = fs.existsSync(fullTranscriptPath) ? fullTranscriptPath : (fs.existsSync(compactTranscriptPath) ? compactTranscriptPath : null);

  const filesMap = new Map();
  const commandsRun = [];
  const keyDecisions = [];
  let userPrompts = [];
  let customNotes = [];

  // Read saved custom notes if any
  if (fs.existsSync(memoryFile)) {
    try {
      const data = JSON.parse(fs.readFileSync(memoryFile, 'utf8'));
      if (Array.isArray(data.customNotes)) customNotes = data.customNotes;
    } catch (e) {}
  }

  if (targetPath) {
    try {
      const raw = fs.readFileSync(targetPath, 'utf8');
      const lines = raw.split('\n');
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const item = JSON.parse(line);
          if (item.type === 'USER_INPUT' && item.content) {
            let text = item.content;
            const match = text.match(/<USER_REQUEST>([\s\S]*?)<\/USER_REQUEST>/);
            if (match) text = match[1];
            text = text.replace(/<ADDITIONAL_METADATA>[\s\S]*?<\/ADDITIONAL_METADATA>/g, '')
                       .replace(/<USER_SETTINGS_CHANGE>[\s\S]*?<\/USER_SETTINGS_CHANGE>/g, '')
                       .trim();
            if (text && !userPrompts.includes(text)) {
              userPrompts.push(text);
            }
          } else if (item.type === 'PLANNER_RESPONSE') {
            if (Array.isArray(item.tool_calls)) {
              for (const call of item.tool_calls) {
                const name = call.name || '';
                const args = call.args || {};
                if (args.CommandLine) {
                  if (!commandsRun.some(c => c.cmd === args.CommandLine)) {
                    commandsRun.push({ cmd: args.CommandLine, action: args.toolAction || args.toolSummary || '' });
                  }
                }
                const file = args.TargetFile || args.AbsolutePath;
                if (file) {
                  const action = name === 'write_to_file' ? 'Created' : name === 'replace_file_content' ? 'Modified' : 'Viewed';
                  filesMap.set(file, action);
                }
                if (args.toolAction && !keyDecisions.includes(args.toolAction)) {
                  keyDecisions.push(args.toolAction);
                }
              }
            }
          }
        } catch (e) {}
      }
    } catch (e) {}
  }

  const filesTouched = Array.from(filesMap.entries()).map(([filePath, action]) => ({ path: filePath, action }));

  return {
    conversationId,
    userPrompts,
    filesTouched,
    commandsRun,
    keyDecisions,
    customNotes,
    summary: userPrompts.length > 0 ? `Accomplished ${userPrompts.length} turn(s). Touched ${filesTouched.length} file(s) and executed ${commandsRun.length} command(s).` : 'No actions recorded yet.'
  };
}

function saveSessionMemoryNote(conversationId, note) {
  if (!note || !note.trim()) return getSessionMemory(conversationId);
  const convDir = path.join(BRAIN_DIR, conversationId);
  if (!fs.existsSync(convDir)) {
    fs.mkdirSync(convDir, { recursive: true });
  }
  const memoryFile = path.join(convDir, 'memory.json');
  let data = { customNotes: [] };
  if (fs.existsSync(memoryFile)) {
    try {
      data = JSON.parse(fs.readFileSync(memoryFile, 'utf8'));
      if (!Array.isArray(data.customNotes)) data.customNotes = [];
    } catch (e) {}
  }
  data.customNotes.push({
    text: note.trim(),
    timestamp: new Date().toISOString()
  });
  fs.writeFileSync(memoryFile, JSON.stringify(data, null, 2), 'utf8');
  return getSessionMemory(conversationId);
}

module.exports = {
  listConversations,
  getConversation,
  deleteConversation,
  getSessionMemory,
  saveSessionMemoryNote,
  CLI_DIR,
  BRAIN_DIR
};
