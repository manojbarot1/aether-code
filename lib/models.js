const { execFile } = require('child_process');

let cachedModels = null;
let lastFetchTime = 0;
const CACHE_TTL_MS = 60 * 1000; // 1 minute

function detectProvider(id) {
  if (id.startsWith('claude')) return 'claude';
  if (id.startsWith('gemini')) return 'gemini';
  if (id.startsWith('gpt') || id.includes('chatgpt') || id.includes('openai')) return 'chatgpt';
  return 'gemini';
}

const DEFAULT_MODELS = [
  // Gemini Models
  { id: 'gemini-3.8-flash-high', name: 'Gemini 3.8 Flash (High)', provider: 'gemini', providerName: 'Gemini' },
  { id: 'gemini-3.8-flash-medium', name: 'Gemini 3.8 Flash (Medium)', provider: 'gemini', providerName: 'Gemini' },
  { id: 'gemini-3.8-flash-low', name: 'Gemini 3.8 Flash (Low)', provider: 'gemini', providerName: 'Gemini' },
  { id: 'gemini-3.7-flash-high', name: 'Gemini 3.7 Flash (High)', provider: 'gemini', providerName: 'Gemini' },
  { id: 'gemini-3.7-flash-medium', name: 'Gemini 3.7 Flash (Medium)', provider: 'gemini', providerName: 'Gemini' },
  { id: 'gemini-3.7-flash-low', name: 'Gemini 3.7 Flash (Low)', provider: 'gemini', providerName: 'Gemini' },
  { id: 'gemini-3.6-flash-high', name: 'Gemini 3.6 Flash (High)', provider: 'gemini', providerName: 'Gemini' },
  { id: 'gemini-3.1-pro-high', name: 'Gemini 3.1 Pro (High)', provider: 'gemini', providerName: 'Gemini' },
  // Claude Models
  { id: 'claude-sonnet-4-6', name: 'Claude Sonnet 4.6 (Thinking)', provider: 'claude', providerName: 'Claude' },
  { id: 'claude-opus-4-6-thinking', name: 'Claude Opus 4.6 (Thinking)', provider: 'claude', providerName: 'Claude' },
  // ChatGPT / OpenAI Models
  { id: 'gpt-oss-120b-medium', name: 'ChatGPT GPT-OSS 120B', provider: 'chatgpt', providerName: 'ChatGPT' }
];

function getModels() {
  return new Promise((resolve) => {
    const now = Date.now();
    if (cachedModels && now - lastFetchTime < CACHE_TTL_MS) {
      return resolve(cachedModels);
    }

    execFile('agy', ['models'], { timeout: 5000 }, (err, stdout) => {
      if (err || !stdout) {
        cachedModels = DEFAULT_MODELS;
        return resolve(cachedModels);
      }

      const models = [];
      const lines = stdout.split('\n');
      for (const rawLine of lines) {
        const line = rawLine.replace(/[\u2800-\u28ff]/g, '').trim();
        if (!line || line.startsWith('Fetching')) continue;
        const match = line.match(/^(\S+)\s+(.+)$/);
        if (match) {
          const id = match[1];
          const name = match[2].trim();
          const provider = detectProvider(id);
          const providerName = provider === 'claude' ? 'Claude' : provider === 'chatgpt' ? 'ChatGPT' : 'Gemini';
          models.push({ id, name, provider, providerName });
        }
      }

      cachedModels = models.length > 0 ? models : DEFAULT_MODELS;
      lastFetchTime = now;
      resolve(cachedModels);
    });
  });
}

module.exports = { getModels, DEFAULT_MODELS, detectProvider };
