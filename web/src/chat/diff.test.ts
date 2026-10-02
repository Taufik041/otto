import { languageOf, parseDiff } from './diff'

it('numbers context, removed and added lines from the hunk header', () => {
  const rows = parseDiff('--- a/p.py\n+++ b/p.py\n@@ -20,4 +20,4 @@ CENT\n def q():\n-    return a > b\n+    return a >= b\n \n')
  expect(rows).toEqual([
    { type: 'hunk', text: '@@ -20,4 +20,4 @@ CENT' },
    { type: 'ctx', old: 20, new: 20, text: 'def q():' },
    { type: 'del', old: 21, new: null, text: '    return a > b' },
    { type: 'add', old: null, new: 21, text: '    return a >= b' },
    { type: 'ctx', old: 22, new: 22, text: '' },
  ])
})

it('a new file and a missing final newline', () => {
  expect(parseDiff('--- /dev/null\n+++ b/n.txt\n@@ -0,0 +1,2 @@\n+x\n+y\n\\ No newline at end of file\n')).toEqual([
    { type: 'hunk', text: '@@ -0,0 +1,2 @@' },
    { type: 'add', old: null, new: 1, text: 'x' },
    { type: 'add', old: null, new: 2, text: 'y' },
    { type: 'note', text: 'No newline at end of file' },
  ])
})

it('languages by extension', () => {
  expect(languageOf('src/inventory/pricing.py')).toBe('python')
  expect(languageOf('docs/PRICING.md')).toBe('markdown')
  expect(languageOf('Dockerfile')).toBe('docker')
  expect(languageOf('LICENSE')).toBeNull()
})
