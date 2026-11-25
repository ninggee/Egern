import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const manifestPath = path.join(root, 'tools', 'module_sources.json');
const converterCommit = 'e4b1cbf2776639f39c2dd581f4e991bed86b765c';
const converterSha256 = 'c5df73e9bdbd0b4591d7616b4dea9b5b2818ef447fb29de0defa9b720aeb2334';
const maxSourceBytes = 5 * 1024 * 1024;
const maxConverterBytes = 1024 * 1024;
const allowedHosts = new Set(['github.com', 'raw.githubusercontent.com', 'txscript.pages.dev', 'yfamilys.com', 'ddgksf2013.top']);
const sensitiveQuery = /(?:token|access[_-]?token|api[_-]?key|secret|password|passwd|authorization|auth)=/i;
const argumentDescriptionWarning = '#!arguments-desc 是整段说明文字、没有按参数名分段，未拆分到各参数的说明里；各参数 description 已回退为参数名本身，整段原文请在原模块里查看。';

function assertSource(source, ids, urls) {
  if (!source || typeof source !== 'object') throw new Error('Source entry must be an object');
  if (!/^[a-z0-9][a-z0-9-]{2,63}$/.test(source.id) || ids.has(source.id)) {
    throw new Error('Source IDs must be unique lowercase slugs');
  }
  const url = new URL(source.url);
  if (url.protocol !== 'https:' || !allowedHosts.has(url.hostname) || url.username || url.password || url.search || url.hash) {
    throw new Error(`Source ${source.id} must be a public HTTPS URL on a reviewed host without credentials or query parameters`);
  }
  if (!/\.(?:sgmodule|module|conf)$/i.test(url.pathname) || urls.has(source.url)) {
    throw new Error(`Source ${source.id} must have a unique .sgmodule, .module, or .conf URL`);
  }
  if (typeof source.name !== 'string' || !source.name.trim()) throw new Error(`Source ${source.id} needs a display name`);
  ids.add(source.id);
  urls.add(source.url);
}

async function readResponse(response, limit, label) {
  if (!response.ok) throw new Error(`${label}: HTTP ${response.status}`);
  const finalUrl = new URL(response.url);
  if (finalUrl.protocol !== 'https:' || !allowedHosts.has(finalUrl.hostname)) {
    throw new Error(`${label}: redirected outside the reviewed HTTPS hosts`);
  }
  const chunks = [];
  let size = 0;
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > limit) throw new Error(`${label}: response exceeds size limit`);
    chunks.push(chunk);
  }
  return new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks));
}

async function loadConverter() {
  const url = `https://raw.githubusercontent.com/IBL3ND/Egern-hub/${converterCommit}/index.html`;
  const html = await readResponse(await fetch(url, {
    headers: { 'User-Agent': 'EgernModuleSync/1.0' }, signal: AbortSignal.timeout(30000)
  }), maxConverterBytes, 'Converter');
  const script = html.match(/<script>([\s\S]*?)<\/script>/i)?.[1];
  if (!script) throw new Error('Pinned converter script is missing');
  const digest = createHash('sha256').update(script, 'utf8').digest('hex');
  if (digest !== converterSha256) throw new Error('Pinned converter checksum mismatch');

  const elements = new Map();
  function makeElement(id) {
    return {
      id, value: '', textContent: '', innerHTML: '', className: '', disabled: false,
      paused: true, muted: true, volume: 0, style: {},
      classList: { add() {}, remove() {}, contains() { return false; } },
      addEventListener() {}, removeEventListener() {}, contains() { return false; },
      play() { return Promise.resolve(); }, pause() {}, select() {}, click() {}, remove() {}
    };
  }
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeElement(id));
      return elements.get(id);
    },
    addEventListener() {},
    removeEventListener() {},
    execCommand() { return true; },
    createElement(tag) { return makeElement(tag); },
    body: { appendChild() {} }
  };
  const sandbox = {
    document,
    navigator: { clipboard: null },
    URL: { createObjectURL() { return ''; }, revokeObjectURL() {} },
    Blob: class Blob {},
    AbortController,
    setTimeout,
    clearTimeout,
    fetch: async () => { throw new Error('Network is disabled inside the converter'); },
    Promise,
    TextEncoder,
    TextDecoder,
    atob,
    btoa,
    console: { log() {}, warn() {}, error() {} }
  };
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox, { timeout: 5000 });
  return sandbox;
}

function moduleText(text, source, converter) {
  if (!text.trim() || /^\s*(?:<!doctype\s+html|<html\b)/i.test(text) || text.includes('\0')) {
    throw new Error('invalid-source');
  }
  const parsed = converter.isQuantumultX(text)
    ? converter.convertQX(text, source.name)
    : converter.convert(text);
  const description = parsed.warnings.includes(argumentDescriptionWarning)
    ? [...text.matchAll(/^[ \t]*#!arguments-desc[ \t]*=[ \t]*([^\r\n]+)$/gim)]
    : [];
  const fullDescription = description.length === 1 ? description[0][1].trim().replace(/\\n/g, '\n') : '';
  const remainingWarnings = fullDescription
    ? parsed.warnings.filter((warning) => warning !== argumentDescriptionWarning)
    : parsed.warnings;
  if (remainingWarnings.length) throw new Error(`warnings-${remainingWarnings.length}`);
  if (!Object.values(parsed.counts).some((count) => count > 0)) throw new Error('no-effective-module-content');
  if (parsed.rewrites.some((rewrite) => rewrite.kind === 'echo' && !rewrite.disabled)) {
    throw new Error('requires-remote-echo-data');
  }
  if (parsed.scriptings.some((script) => script.binary_check && !script.binary_body && !script.disabled)) {
    throw new Error('requires-remote-script-inspection');
  }

  const meta = parsed.buildArgs[0];
  if (!meta.name) meta.name = source.name.replace(/\.(?:sgmodule|module|conf)$/i, '');
  let output = converter.buildYaml.apply(null, parsed.buildArgs);
  if (fullDescription) output = `${output.trimEnd()}\ncompat_arguments_desc: ${JSON.stringify(fullDescription)}\n`;
  if (!output.trim() || sensitiveQuery.test(output) || /https?:\/\/[^\s/@]+:[^\s/@]+@/i.test(output)) {
    throw new Error('empty-or-sensitive-output');
  }
  return output;
}

async function convertSource(source, converter, outputDir) {
  try {
    const input = await readResponse(await fetch(source.url, {
      headers: { 'User-Agent': 'Surge/5.0 EgernModuleSync/1.0', Accept: 'text/plain, application/octet-stream;q=0.9' },
      signal: AbortSignal.timeout(30000)
    }), maxSourceBytes, `Source ${source.id}`);
    const output = moduleText(input, source, converter);
    await writeFile(path.join(outputDir, `${source.id}.yaml`), output, 'utf8');
    return { id: source.id, status: 'converted', bytes: Buffer.byteLength(output) };
  } catch (error) {
    const reason = String(error.message || error);
    const known = new Set(['invalid-source', 'no-effective-module-content', 'requires-remote-echo-data', 'requires-remote-script-inspection', 'empty-or-sensitive-output']);
    const status = /^warnings-\d+$/.test(reason) || known.has(reason) ? reason : 'fetch-or-conversion-failed';
    return { id: source.id, status };
  }
}

async function main() {
  const outputFlag = process.argv.indexOf('--output');
  if (outputFlag < 0 || !process.argv[outputFlag + 1]) throw new Error('Usage: node tools/sync_converted_modules.mjs --output <directory>');
  const outputDir = path.resolve(process.argv[outputFlag + 1]);
  const manifestBytes = await readFile(manifestPath);
  const manifest = JSON.parse(manifestBytes.toString('utf8'));
  if (!Array.isArray(manifest.sources)) throw new Error('The source manifest must contain a sources array');
  const ids = new Set();
  const urls = new Set();
  for (const source of manifest.sources) assertSource(source, ids, urls);
  await mkdir(outputDir, { recursive: true });
  await writeFile(path.join(outputDir, 'manifest.sha256'), `${createHash('sha256').update(manifestBytes).digest('hex')}\n`, 'utf8');
  const converter = manifest.sources.length ? await loadConverter() : null;
  let next = 0;
  const results = [];
  async function worker() {
    while (true) {
      const index = next++;
      if (index >= manifest.sources.length) return;
      results.push(await convertSource(manifest.sources[index], converter, outputDir));
    }
  }
  await Promise.all(Array.from({ length: 6 }, worker));
  results.sort((left, right) => left.id.localeCompare(right.id));
  const counts = new Map();
  for (const result of results) counts.set(result.status, (counts.get(result.status) || 0) + 1);
  const lines = ['# Converted module sync', '', `Sources: ${results.length}`, `Converted: ${counts.get('converted') || 0}`, '', '| Source ID | Result |', '| --- | --- |'];
  for (const result of results) lines.push(`| ${result.id} | ${result.status} |`);
  await writeFile(path.join(outputDir, 'summary.md'), `${lines.join('\n')}\n`, 'utf8');
  console.log(`Converted ${counts.get('converted') || 0}/${results.length}; skipped ${results.length - (counts.get('converted') || 0)}. Details use source IDs only.`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
