import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const script = resolve(dirname(fileURLToPath(import.meta.url)), 'dev.ps1')
const passwords = ['superuser', 'api', 'worker', 'migration', 'backup'].map(role => `postgres_${role}_password`)
const urls = ['api', 'worker', 'migration'].map(role => `${role}_database_url`)
const names = [...passwords, ...urls].sort()

function project() {
  const root = mkdtempSync(join(tmpdir(), 'guichuhub-dev-test-'))
  mkdirSync(join(root, 'backend'))
  mkdirSync(join(root, 'frontend'))
  writeFileSync(join(root, 'compose.dev.yml'), 'services: {}\n')
  writeFileSync(join(root, 'backend', 'uv.lock'), 'backend-lock-one\n')
  writeFileSync(join(root, 'frontend', 'package-lock.json'), 'frontend-lock-one\n')
  return root
}

function init(root, env = {}) {
  return spawnSync('pwsh', ['-NoProfile', '-NonInteractive', '-File', script, '-Action', 'init', '-ProjectRoot', root], {
    encoding: 'utf8', timeout: 30000, env: { ...process.env, ...env },
  })
}

test('rejects inherited Compose overrides before creating local credentials', () => {
  for (const name of ['KICHU_DEV_SECRETS_DIR', 'KICHU_DEV_BACKEND_DEPS', 'KICHU_DEV_FRONTEND_DEPS']) {
    const root = project()
    const result = init(root, { [name]: 'external-value' })
    assert.notEqual(result.status, 0, `${name} must not override the isolated environment`)
    assert.deepEqual(readdirSync(root).sort(), ['backend', 'compose.dev.yml', 'frontend'])
  }
})

function credentials(root) {
  return Object.fromEntries(names.map(name => [name, readFileSync(join(root, 'runtime', 'dev', 'secrets', name), 'utf8')]))
}

test('initializes separate role secrets without BOMs or printing passwords', () => {
  const root = project()
  const result = init(root)
  assert.equal(result.status, 0, result.stdout + result.stderr)
  assert.deepEqual(readdirSync(join(root, 'runtime', 'dev', 'secrets')).sort(), names)
  const values = credentials(root)
  assert.equal(new Set(passwords.map(name => values[name])).size, 5)
  for (const name of passwords) {
    assert.match(values[name], /^[a-f0-9]{64}$/)
    assert.ok(!(result.stdout + result.stderr).includes(values[name]))
  }
  for (const role of ['api', 'worker', 'migration']) {
    assert.equal(values[`${role}_database_url`], `postgresql+psycopg://kichu_${role}:${values[`postgres_${role}_password`]}@postgres:5432/kichu`)
  }
})

test('reuses credentials while changing only dependency cache identities when locks change', () => {
  const root = project()
  assert.equal(init(root).status, 0)
  const before = credentials(root)
  const config = join(root, 'runtime', 'dev', 'compose.env')
  const first = readFileSync(config, 'utf8')
  assert.equal(init(root).status, 0)
  assert.deepEqual(credentials(root), before)
  assert.equal(readFileSync(config, 'utf8'), first)
  writeFileSync(join(root, 'frontend', 'package-lock.json'), 'frontend-lock-two\n')
  assert.equal(init(root).status, 0)
  assert.deepEqual(credentials(root), before)
  const second = readFileSync(config, 'utf8')
  assert.notEqual(first, second)
  assert.equal(first.match(/^KICHU_DEV_BACKEND_DEPS=.*$/m)[0], second.match(/^KICHU_DEV_BACKEND_DEPS=.*$/m)[0])
  const expected = createHash('sha256').update('frontend-lock-two\n').digest('hex').slice(0, 12)
  assert.ok(second.includes(`KICHU_DEV_FRONTEND_DEPS=${expected}`))
})

test('rejects partial credentials without overwriting or filling them', () => {
  const root = project()
  const secrets = join(root, 'runtime', 'dev', 'secrets')
  mkdirSync(secrets, { recursive: true })
  writeFileSync(join(secrets, 'postgres_api_password'), 'keep-existing-password')
  const result = init(root)
  assert.notEqual(result.status, 0)
  assert.deepEqual(readdirSync(secrets), ['postgres_api_password'])
  assert.equal(readFileSync(join(secrets, 'postgres_api_password'), 'utf8'), 'keep-existing-password')
  assert.ok(!(result.stdout + result.stderr).includes('keep-existing-password'))
})

test('refuses to generate new credentials over an existing database directory', () => {
  const root = project()
  const database = join(root, 'runtime', 'dev', 'postgres')
  mkdirSync(database, { recursive: true })
  writeFileSync(join(database, 'PG_VERSION'), '16\n')
  const result = init(root)
  assert.notEqual(result.status, 0)
  assert.equal(readFileSync(join(database, 'PG_VERSION'), 'utf8'), '16\n')
  assert.deepEqual(readdirSync(join(root, 'runtime', 'dev')), ['postgres'])
})

test('rejects role URL mismatches without exposing credentials or changing files', () => {
  const root = project()
  assert.equal(init(root).status, 0)
  const secrets = join(root, 'runtime', 'dev', 'secrets')
  writeFileSync(join(secrets, 'api_database_url'), readFileSync(join(secrets, 'worker_database_url')))
  const before = credentials(root)
  const result = init(root)
  assert.notEqual(result.status, 0)
  assert.deepEqual(credentials(root), before)
  for (const name of passwords) assert.ok(!(result.stdout + result.stderr).includes(before[name]))
})
