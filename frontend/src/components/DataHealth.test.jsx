import { render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'

import DataHealth from './DataHealth'
import { api } from '../utils/api'

vi.mock('../utils/api', () => ({
  api: { getDevStats: vi.fn() },
}))

beforeEach(() => {
  api.getDevStats.mockResolvedValue({
    success: true,
    data: {
      alembic_revision: '0001_postgresql_v3_baseline',
      video_obs_batches: 2,
      video_obs_rows: 3,
      videos: 4,
      ups: 5,
      crawl_runs: { success: 1, running: 0 },
      stale_running: [],
    },
  })
})

test('labels the health source and migration revision as PostgreSQL', async () => {
  render(<DataHealth />)

  expect(await screen.findByText(/PostgreSQL 历史仓库健康概览/)).toBeInTheDocument()
  expect(screen.getByText('Alembic 版本')).toBeInTheDocument()
  expect(screen.getByText('0001_postgresql_v3_baseline')).toBeInTheDocument()
  expect(screen.queryByText(/SQLite/)).not.toBeInTheDocument()
})
