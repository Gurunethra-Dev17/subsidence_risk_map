export function publicHttpUrl(value: string, base: string): URL {
  const url = new URL(value, base)
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
  if ((url.protocol !== 'https:' && !(local && url.protocol === 'http:')) ||
    url.username || url.password || [...url.searchParams.keys()].some((key) => /token|secret|password|signature|api[_-]?key/i.test(key))) {
    throw new Error('Use an HTTPS or loopback URL without credentials.')
  }
  return url
}
