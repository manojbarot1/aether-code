const { spawn } = require('child_process');
const readline = require('readline');
const EventEmitter = require('events');
const fs = require('fs');
const path = require('path');
const os = require('os');

const BRAIN_DIR = path.join(os.homedir(), '.gemini', 'antigravity-cli', 'brain');

// Active processes mapped by conversationId or temp session key
const activeProcesses = new Map();

function runTurn({
  prompt,
  conversationId = null,
  model = null,
  effort = null,
  skipPermissions = true,
  sandbox = false,
  mode = null,
  cwd = process.env.HOME || '/home/manojb'
}) {
  const emitter = new EventEmitter();

  const args = ['--output-format', 'stream-json'];

  if (conversationId) {
    args.push('--conversation', conversationId);
  }

  if (model) {
    args.push('--model', model);
  }

  if (effort && ['low', 'medium', 'high', 'max'].includes(effort)) {
    args.push(`--effort=${effort}`);
  }

  if (skipPermissions) {
    args.push('--dangerously-skip-permissions');
  }

  if (sandbox) {
    args.push('--sandbox');
  }

  if (mode) {
    args.push('--mode', mode);
  }

  // Pass prompt to --print
  args.push(`--print=${prompt}`);

  const child = spawn('agy', args, {
    cwd: cwd,
    env: { ...process.env, PAGER: 'cat' }
  });

  const sessionKey = conversationId || `temp_${Date.now()}`;
  activeProcesses.set(sessionKey, child);

  let currentConversationId = conversationId;
  let accumulatedResponse = '';
  let accumulatedThought = '';
  let hasEnded = false;
  let transcriptTimer = null;
  let lastTranscriptBytes = 0;
  let seenThinking = new Set();

  function startTranscriptWatcher(convId) {
    if (transcriptTimer || !convId) return;
    const fullTranscriptPath = path.join(BRAIN_DIR, convId, '.system_generated', 'logs', 'transcript_full.jsonl');
    const compactTranscriptPath = path.join(BRAIN_DIR, convId, '.system_generated', 'logs', 'transcript.jsonl');

    transcriptTimer = setInterval(() => {
      const targetPath = fs.existsSync(fullTranscriptPath) ? fullTranscriptPath : (fs.existsSync(compactTranscriptPath) ? compactTranscriptPath : null);
      if (!targetPath) return;

      try {
        const stats = fs.statSync(targetPath);
        if (stats.size > lastTranscriptBytes) {
          const raw = fs.readFileSync(targetPath, 'utf8');
          lastTranscriptBytes = stats.size;
          const lines = raw.split('\n');
          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const item = JSON.parse(line);
              if (item.thinking && !seenThinking.has(item.thinking)) {
                seenThinking.add(item.thinking);
                accumulatedThought += item.thinking + '\n\n';
                emitter.emit('event', {
                  type: 'thought',
                  conversationId: convId,
                  text: item.thinking,
                  fullThought: accumulatedThought
                });
              }
              if (item.tool_calls && Array.isArray(item.tool_calls)) {
                for (const tc of item.tool_calls) {
                  const action = tc.args?.toolAction || tc.args?.toolSummary;
                  if (action && !seenThinking.has(action)) {
                    seenThinking.add(action);
                    const note = `💭 Intent: ${action}\n`;
                    accumulatedThought += note;
                    emitter.emit('event', {
                      type: 'thought',
                      conversationId: convId,
                      text: note,
                      fullThought: accumulatedThought
                    });
                  }
                }
              }
            } catch (e) {}
          }
        }
      } catch (err) {}
    }, 80);
  }

  if (currentConversationId) {
    startTranscriptWatcher(currentConversationId);
  }

  const rl = readline.createInterface({
    input: child.stdout,
    crlfDelay: Infinity
  });

  rl.on('line', (line) => {
    line = line.trim();
    if (!line) return;

    try {
      const eventObj = JSON.parse(line);

      if (eventObj.event === 'init') {
        currentConversationId = eventObj.conversation_id || currentConversationId;
        if (currentConversationId && sessionKey !== currentConversationId) {
          activeProcesses.set(currentConversationId, child);
        }
        startTranscriptWatcher(currentConversationId);
        emitter.emit('event', {
          type: 'init',
          conversationId: currentConversationId,
          cwd: eventObj.init?.cwd,
          model: eventObj.init?.model
        });
        emitter.emit('event', {
          type: 'activity',
          conversationId: currentConversationId,
          activity: 'Agent initialized. Analyzing prompt...'
        });
      } else if (eventObj.event === 'step_update' && eventObj.step_update) {
        const su = eventObj.step_update;

        if (su.step_type === 'agent_response') {
          if (su.text_delta) {
            accumulatedResponse += su.text_delta;
            emitter.emit('event', {
              type: 'delta',
              conversationId: currentConversationId,
              text: su.text_delta,
              fullText: accumulatedResponse
            });
            emitter.emit('event', {
              type: 'activity',
              conversationId: currentConversationId,
              activity: 'Generating response stream...'
            });
          }
        } else if (su.step_type === 'thinking') {
          if (su.text_delta) {
            accumulatedThought += su.text_delta;
            emitter.emit('event', {
              type: 'thought',
              conversationId: currentConversationId,
              text: su.text_delta,
              fullThought: accumulatedThought
            });
          }
        } else if (su.step_type === 'tool') {
          const toolName = su.tool_name || su.tool_info?.name || 'tool';
          const cmd = su.tool_info?.parameters?.CommandLine;
          const actionDesc = su.tool_info?.parameters?.toolAction || su.tool_info?.parameters?.toolSummary;

          // If tool provides action or summary description, surface it as live thinking
          if (actionDesc && su.state === 'ACTIVE' && !accumulatedThought.includes(actionDesc)) {
            const thoughtPiece = `> Intent: ${actionDesc}\n`;
            accumulatedThought += thoughtPiece;
            emitter.emit('event', {
              type: 'thought',
              conversationId: currentConversationId,
              text: thoughtPiece,
              fullThought: accumulatedThought
            });
          }

          // Emit live activity status
          emitter.emit('event', {
            type: 'activity',
            conversationId: currentConversationId,
            activity: su.state === 'ACTIVE'
              ? (cmd ? `Running Bash: ${cmd}` : `Executing ${toolName}...`)
              : `Completed ${toolName} in ${su.duration_seconds ? su.duration_seconds.toFixed(2) + 's' : '0.0s'}`
          });

          // Emit live tool execution with complete information
          emitter.emit('event', {
            type: 'tool',
            conversationId: currentConversationId,
            toolName: toolName,
            stepIndex: su.step_index,
            state: su.state, // 'ACTIVE' or 'DONE'
            duration: su.duration_seconds,
            toolInfo: su.tool_info
          });
        }
      } else if (eventObj.event === 'result' && eventObj.result) {
        const res = eventObj.result;
        hasEnded = true;
        if (transcriptTimer) clearInterval(transcriptTimer);

        emitter.emit('event', {
          type: 'activity',
          conversationId: res.conversation_id || currentConversationId,
          activity: 'Done'
        });

        emitter.emit('event', {
          type: 'result',
          conversationId: res.conversation_id || currentConversationId,
          status: res.status,
          response: res.response || accumulatedResponse,
          duration: res.duration_seconds,
          usage: res.usage,
          error: res.error
        });
      }
    } catch (e) {
      if (line.includes('error:')) {
        emitter.emit('event', { type: 'error', error: line });
      }
    }
  });

  let stderrOutput = '';
  child.stderr.on('data', (data) => {
    const text = data.toString();
    stderrOutput += text;
    emitter.emit('event', { type: 'stderr', text });
  });

  child.on('error', (err) => {
    if (transcriptTimer) clearInterval(transcriptTimer);
    emitter.emit('event', { type: 'error', error: err.message });
  });

  child.on('close', (code) => {
    if (transcriptTimer) clearInterval(transcriptTimer);
    activeProcesses.delete(sessionKey);
    if (currentConversationId) {
      activeProcesses.delete(currentConversationId);
    }

    if (!hasEnded) {
      emitter.emit('event', {
        type: 'done',
        code,
        conversationId: currentConversationId,
        response: accumulatedResponse,
        stderr: stderrOutput
      });
    }
  });

  emitter.cancel = () => {
    if (transcriptTimer) clearInterval(transcriptTimer);
    try {
      child.kill('SIGINT');
      setTimeout(() => {
        if (!child.killed) child.kill('SIGTERM');
      }, 1000);
    } catch (e) {}
  };

  return emitter;
}

function cancelTurn(conversationId) {
  const child = activeProcesses.get(conversationId);
  if (child) {
    try {
      child.kill('SIGINT');
      setTimeout(() => {
        if (!child.killed) child.kill('SIGKILL');
      }, 1000);
    } catch (e) {}
    activeProcesses.delete(conversationId);
    return true;
  }
  return false;
}

module.exports = {
  runTurn,
  cancelTurn
};
