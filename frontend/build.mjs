import {build} from 'esbuild';
import {mkdir, readFile, writeFile, copyFile, readdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.dirname(fileURLToPath(import.meta.url));
const output=path.resolve(root,'../static/vendor/visual');
const names=['globe','timeline','network','flow','diff'];
const selected=process.argv.includes('--entry')?[process.argv[process.argv.indexOf('--entry')+1]]:names;
if(selected.some(name=>!names.includes(name)))throw new Error('Unknown visual entry');
await mkdir(output,{recursive:true});
for(const name of selected){
  let source=path.join(root,name+'.js');
  try{await readFile(source);}catch(error){if(error.code==='ENOENT'&&!process.argv.includes('--entry'))continue;throw error;}
  const result=await build({entryPoints:[source],outfile:path.join(output,name+'.js'),bundle:true,format:'esm',target:'es2022',minify:true,legalComments:'eof',metafile:true});
  if(Object.keys(result.metafile.inputs).some(input=>/(^|[\\/])fixture[.]|work[\\/]prototypes[\\/]/.test(input)))throw new Error('Prototype fixture cannot enter application assets');
}
// Copy shared assets without cleaning the output: single-entry builds preserve peers.
for(const [from,to] of [['@xyflow/react/dist/style.css','flow.css'],['diff2html/bundles/css/diff2html.min.css','diff.css'],['elkjs/lib/elk-worker.min.js','elk-worker.min.js']])
  await copyFile(path.join(root,'node_modules',from),path.join(output,to));
await writeFile(path.join(output,'cytoscape-csp.css'),'.__________cytoscape_container{position:relative}\n');
const licenseRoot=path.join(output,'licenses');await mkdir(licenseRoot,{recursive:true});
await copyFile(path.join(root,'prototype-LICENSE.txt'),path.join(licenseRoot,'prototype-LICENSE.txt'));

// Include all installed runtime transitive licenses, and build-tool licenses.
for(const entry of await readdir(path.join(root,'node_modules'),{withFileTypes:true})){
  if(!entry.isDirectory()||entry.name.startsWith('.'))continue;
  const packages=entry.name.startsWith('@')?(await readdir(path.join(root,'node_modules',entry.name))).map(n=>entry.name+'/'+n):[entry.name];
  for(const pkg of packages){
    const directory=path.join(root,'node_modules',pkg);
    for(const name of await readdir(directory))if(/^(license|licence|notice|copying)(\.|$)/i.test(name))
      await copyFile(path.join(directory,name),path.join(licenseRoot,pkg.replaceAll('/','-')+'-'+name));
  }
}
await writeFile(path.join(licenseRoot,'ELK-SOURCE.txt'),'elkjs 0.12.1 is distributed under EPL-2.0, with conditional secondary-license provisions in upstream source.\nExact source release: https://registry.npmjs.org/elkjs/-/elkjs-0.12.1.tgz\nUpstream: https://github.com/kieler/elkjs/tree/v0.12.1\nNo ELK source modifications. API and classic worker must remain the same version.\n');
