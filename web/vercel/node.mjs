// Node's (req, res) and the web's Request/Response: the Vercel function and Vite's dev and
// preview servers hand POST /api/wake to the same handler (wake.mjs) through these.

/** A web Request from a Node request. */
export async function toRequest(req) {
  const chunks = []
  for await (const c of req) chunks.push(c)
  const headers = new Headers()
  for (const [k, v] of Object.entries(req.headers)) if (v !== undefined) headers.set(k, Array.isArray(v) ? v.join(', ') : v)
  const proto = req.headers['x-forwarded-proto'] || (req.socket?.encrypted ? 'https' : 'http')
  const host = req.headers['x-forwarded-host'] || req.headers.host || 'localhost'
  const body = req.method === 'GET' || req.method === 'HEAD' ? undefined : Buffer.concat(chunks)
  return new Request(`${proto}://${host}${req.url}`, { method: req.method, headers, body })
}

/** The client's address: the first X-Forwarded-For hop (Vercel sets it), else the socket's. */
export const clientIp = (req) =>
  String(req.headers['x-forwarded-for'] || '').split(',')[0].trim() || req.socket?.remoteAddress || 'unknown'

/** Write a web Response to a Node response. */
export async function writeResponse(res, response) {
  res.statusCode = response.status
  response.headers.forEach((v, k) => res.setHeader(k, v))
  res.end(Buffer.from(await response.arrayBuffer()))
}
