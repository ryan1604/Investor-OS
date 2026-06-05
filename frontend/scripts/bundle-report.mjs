import { brotliCompressSync, gzipSync } from 'node:zlib'
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { dirname, extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const distDir = join(scriptDir, '..', 'dist')
const outputPath = join(scriptDir, '..', '..', 'docs', 'frontend-bundle-baseline.json')

const assets = collectAssets(distDir)
  .filter((asset) => ['.css', '.js'].includes(extname(asset)))
  .map((asset) => {
    const bytes = readFileSync(asset)
    const path = relative(distDir, asset).replaceAll('\\', '/')

    return {
      path,
      type: extname(asset).slice(1),
      bytes: bytes.length,
      gzip_bytes: gzipSync(bytes).length,
      brotli_bytes: brotliCompressSync(bytes).length,
      initial: path.startsWith('assets/index-'),
    }
  })
  .sort((left, right) => right.bytes - left.bytes)

const totals = assets.reduce(
  (summary, asset) => ({
    bytes: summary.bytes + asset.bytes,
    gzip_bytes: summary.gzip_bytes + asset.gzip_bytes,
    brotli_bytes: summary.brotli_bytes + asset.brotli_bytes,
  }),
  { bytes: 0, gzip_bytes: 0, brotli_bytes: 0 },
)

const report = {
  generated_at: new Date().toISOString(),
  budgets: {
    initial_js_gzip_bytes: 180_000,
    total_js_gzip_bytes: 320_000,
    total_css_gzip_bytes: 60_000,
  },
  totals,
  initial: summarize(assets.filter((asset) => asset.initial)),
  by_type: {
    js: summarize(assets.filter((asset) => asset.type === 'js')),
    css: summarize(assets.filter((asset) => asset.type === 'css')),
  },
  assets,
}

writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`)
console.log(JSON.stringify(report, null, 2))

function collectAssets(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name)
    return statSync(path).isDirectory() ? collectAssets(path) : [path]
  })
}

function summarize(items) {
  return items.reduce(
    (summary, asset) => ({
      files: summary.files + 1,
      bytes: summary.bytes + asset.bytes,
      gzip_bytes: summary.gzip_bytes + asset.gzip_bytes,
      brotli_bytes: summary.brotli_bytes + asset.brotli_bytes,
    }),
    { files: 0, bytes: 0, gzip_bytes: 0, brotli_bytes: 0 },
  )
}
