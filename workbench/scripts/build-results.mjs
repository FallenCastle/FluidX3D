import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
await build({entryPoints:[root+'web/src/results.js'],bundle:true,minify:true,format:'iife',target:['safari16','chrome110'],outfile:root+'web/results.js',legalComments:'linked',loader:{'.glsl':'text'}});
