const beijingTime = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})

export function formatVideoPublishTime(value) {
  const timestamp = Number(value)
  if (!Number.isFinite(timestamp) || timestamp <= 0) return null
  const date = new Date(timestamp < 1e12 ? timestamp * 1000 : timestamp)
  if (Number.isNaN(date.getTime())) return null
  const parts = Object.fromEntries(beijingTime.formatToParts(date).map(({ type, value: part }) => [type, part]))
  return { iso: date.toISOString(), text: `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}` }
}

export function videoRate(value, views) {
  if (value == null || views == null || !Number.isFinite(Number(value)) || !Number.isFinite(Number(views)) || Number(views) <= 0 || Number(value) < 0) return '—'
  return `${(Number(value) / Number(views) * 100).toFixed(1)}%`
}
