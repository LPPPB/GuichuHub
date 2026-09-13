export function proxyImage(url) {
  if (!url) return ''
  if (url.startsWith('/api/proxy/image')) return url
  if (url.includes('hdslb.com') || url.includes('biliimg.com') || url.includes('bilibili.com')) {
    return `/api/proxy/image?url=${encodeURIComponent(url)}`
  }
  return url
}
