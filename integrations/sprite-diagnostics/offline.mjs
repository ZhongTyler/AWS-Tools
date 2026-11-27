import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dgram from 'node:dgram';
import cp from 'node:child_process';
import dns from 'node:dns';
import http2 from 'node:http2';
import {syncBuiltinESMExports} from 'node:module';

const root = process.cwd();
os.homedir = () => path.join(root, 'home');
const attempts = [];
function deny(name) {
  return () => { attempts.push(name); throw new Error('Offline operation blocked'); };
}
globalThis.fetch = deny('fetch');
for (const [name, mod] of [['http',http],['https',https]]) {
  mod.request = deny(name+'.request'); mod.get = deny(name+'.get');
}
net.connect = deny('net.connect'); net.createConnection = deny('net.createConnection');
net.Socket.prototype.connect = deny('socket.connect');
tls.connect = deny('tls.connect'); dgram.createSocket = deny('dgram.createSocket');
for (const name of ['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork'])
  cp[name] = deny('child_process.'+name);
for (const name of ['lookup','lookupService','resolve','resolve4','resolve6','resolveAny','resolveCaa','resolveCname','resolveMx','resolveNaptr','resolveNs','resolvePtr','resolveSoa','resolveSrv','resolveTxt','reverse'])
  if (typeof dns[name] === 'function') dns[name] = deny('dns.'+name);
for (const name of Object.keys(dns.promises))
  if (typeof dns.promises[name] === 'function' && name !== 'Resolver') dns.promises[name] = deny('dns.promises.'+name);
for (const proto of [dns.Resolver.prototype, dns.promises.Resolver.prototype])
  for (const name of Object.getOwnPropertyNames(proto))
    if (name !== 'constructor' && typeof proto[name] === 'function') proto[name] = deny('dns.resolver.'+name);
http2.connect = deny('http2.connect');
syncBuiltinESMExports();
const options = JSON.parse(fs.readFileSync('operation.json', 'utf8'));
try {
  await import('./vendor/dist/toolbox/sprite.js');
  await import('./vendor/dist/toolbox/sprite-analysis.js');
  const {TOOLS} = await import('./vendor/dist/toolbox/registry.js');
  if (!['metrics','loop','slice','export'].includes(options.action)) throw new Error('Unknown offline action');
  const command = TOOLS.find(t => t.group === 'sprite' && t.name === options.action);
  const flags = new Map([['--grid', options.columns+'x'+options.rows]]);
  if (options.action === 'slice') flags.set('--frames', options.columns*options.rows);
  if (options.action === 'export') {
    flags.set('--fps', 1000/options.durations_ms[0]);
    flags.set('--pivot', options.pivot.join(','));
  }
  const context = {jsonOut:true,vis:{enabled:false},outDir:path.join(root,'artifacts'),globals:{quiet:true,engine:options.action==='export'?'godot':undefined}};
  process.exitCode = await command.run(context, {args:['input.png'],flags});
} catch (error) {
  process.exitCode = 2;
  process.stderr.write(String(error.message).slice(0, 500)+'\n');
} finally {
  fs.writeFileSync('guard.json', JSON.stringify({attempts})+'\n');
}
