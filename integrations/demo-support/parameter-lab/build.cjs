const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const root = __dirname;
const library = fs.readFileSync(path.join(root, 'vendor/lil-gui.esm.js'));
const libraryUrl = `data:text/javascript;base64,${library.toString('base64')}`;
const adapter = fs.readFileSync(path.join(root, 'parameter-lab.mjs'), 'utf8');
const source = fs.readFileSync(path.join(root, 'sample.mjs'), 'utf8');
const imports = "import GUI from './vendor/lil-gui.esm.js';\nimport {createParameterLab} from './parameter-lab.mjs';\n";
if (!source.startsWith(imports)) throw new Error('Sample imports changed; inspect build mapping');
const script = `import GUI from '${libraryUrl}';\n${adapter}\n${source.slice(imports.length)}`;
const marker = '<script type="module" src="./sample.mjs"></script>';
const html = fs.readFileSync(path.join(root, 'sample.html'), 'utf8');
if (html.split(marker).length !== 2) throw new Error('Sample entry marker changed');
const license = fs.readFileSync(path.join(root, 'vendor/LICENSE'), 'utf8');
const output = html.replace(marker, `<!-- lil-gui 0.21.0\n${license}\n-->\n<script type="module">${script.replace(/<\/script/gi, '<\\/script')}</script>`);
fs.writeFileSync(path.join(root, 'standalone.html'), output);
const result = {
  output: 'standalone.html', bytes: Buffer.byteLength(output),
  sha256: crypto.createHash('sha256').update(output).digest('hex'),
  library: {name: 'lil-gui', version: '0.21.0', license: 'MIT', sha256: crypto.createHash('sha256').update(library).digest('hex')},
};
fs.writeFileSync(path.join(root, 'build.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result));
