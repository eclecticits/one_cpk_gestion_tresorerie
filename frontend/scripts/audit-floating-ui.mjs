import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const root = new URL('..', import.meta.url).pathname
const srcDir = join(root, 'src')
const failures = []

const floatingSelectorPattern = /\.(modal|modalOverlay|overlay|backdrop|dialog|drawer|sheet)([\s,{.#:]|$)/i
const ignoreSelectorPattern = /\.(aiPopover|actionsMenu|dropdown|menuBackdrop|controlPanel)([\s,{.#:]|$)/i
const ignoredFiles = new Set([
  'components/Layout.module.css',
])

for (const file of walk(srcDir)) {
  if (!file.endsWith('.css')) continue
  if (ignoredFiles.has(format(file))) continue

  const css = readFileSync(file, 'utf8')
  for (const block of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = block[1].trim()
    const body = block[2]

    if (!floatingSelectorPattern.test(selector) || ignoreSelectorPattern.test(selector)) continue
    if (!/position\s*:\s*fixed/.test(body)) continue

    const zIndexMatch = body.match(/z-index\s*:\s*([^;]+)/)
    if (!zIndexMatch) {
      failures.push(`${format(file)} :: ${selector} has position: fixed without z-index`)
      continue
    }

    const zIndex = Number(zIndexMatch[1].trim())
    if (Number.isFinite(zIndex) && zIndex < 1000) {
      failures.push(`${format(file)} :: ${selector} has z-index ${zIndex}, below the app shell/sidebar`)
    }

    if (!/overflow-y\s*:\s*auto|overflow\s*:\s*auto/.test(body)) {
      failures.push(`${format(file)} :: ${selector} should allow viewport scrolling for low-height screens`)
    }
  }
}

const responsiveModal = readFileSync(join(srcDir, 'components', 'ResponsiveModal.tsx'), 'utf8')
const requiredSnippets = [
  'createPortal',
  'document.body',
  'role="dialog"',
  'aria-modal="true"',
  'aria-labelledby',
]

for (const snippet of requiredSnippets) {
  if (!responsiveModal.includes(snippet)) {
    failures.push(`components/ResponsiveModal.tsx is missing ${snippet}`)
  }
}

if (failures.length > 0) {
  console.error('Floating UI audit failed:')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exit(1)
}

console.log('Floating UI audit passed.')

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const file = join(dir, entry)
    const stat = statSync(file)
    if (stat.isDirectory()) {
      yield* walk(file)
    } else {
      yield file
    }
  }
}

function format(file) {
  return relative(srcDir, file).replaceAll('\\', '/')
}
