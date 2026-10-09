import { expect, it } from 'vitest'
import { formatVideoPublishTime, videoRate } from './videoCardMeta'

it('formats publication timestamps in Beijing time, independent of browser timezone', () => {
  expect(formatVideoPublishTime(1700000000)).toEqual({ iso: '2023-11-14T22:13:20.000Z', text: '2023-11-15 06:13' })
  expect(formatVideoPublishTime(1700000000000)).toEqual(formatVideoPublishTime(1700000000))
})

it('does not invent publication times for missing or invalid timestamps', () => {
  for (const value of [null, undefined, '', 0, -1, 'invalid', Infinity, 1e20]) {
    expect(formatVideoPublishTime(value)).toBeNull()
  }
})

it('distinguishes missing interaction counts from measured zero', () => {
  expect(videoRate(null, 1000)).toBe('—')
  expect(videoRate(undefined, 1000)).toBe('—')
  expect(videoRate(20, 0)).toBe('—')
  expect(videoRate(0, 1000)).toBe('0.0%')
  expect(videoRate(43, 1000)).toBe('4.3%')
})
