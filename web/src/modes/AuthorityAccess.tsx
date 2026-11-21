import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { LockKeyhole, ShieldCheck } from 'lucide-react'
import { AuthorityError } from '../api/authorityErrors'
import type { AuthoritySession } from '../api/authority'
import { config } from '../config'
import Modal from '../panels/Modal'

export default function AuthorityAccess({ session, signIn, signOut }: {
  session: AuthoritySession | null
  signIn: (session: AuthoritySession) => void
  signOut: () => void
}) {
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])

  const close = () => {
    request.current?.abort()
    setOpen(false)
    setPending(false)
    setError('')
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const password = form.elements.namedItem('token') as HTMLInputElement
    const token = password.value.trim()
    const archive = (form.elements.namedItem('archive') as HTMLInputElement).value.trim()
    password.value = ''
    if (!token) { setError('Enter your authority token.'); return }
    const controller = new AbortController()
    request.current?.abort()
    request.current = controller
    setPending(true)
    setError('')
    try {
      const { openAuthority } = await import('../api/authority')
      const authorized = await openAuthority(token, archive, controller.signal)
      if (controller.signal.aborted) { authorized.close(); return }
      signIn(authorized)
      close()
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof AuthorityError ? failure.message : 'Authority access could not be verified.')
    } finally {
      if (!controller.signal.aborted) setPending(false)
    }
  }

  return (
    <div className="mode-switch">
      <span className={'public-badge' + (session ? ' mode-authority' : '')}><ShieldCheck size={15} />{session ? 'Authority mode' : 'Public mode'}</span>
      {session
        ? <button className="header-button" type="button" onClick={signOut}>Sign out</button>
        : <button className="header-button" type="button" onClick={() => setOpen(true)}><LockKeyhole size={14} /> Authority access</button>}
      {open && <Modal title="Authority access" onClose={close}>
        <div className="dialog-content">
          {config.mock ? <p role="status">Authority access is unavailable in mock mode. Building data requires a live, authenticated API.</p> : (
            <form className="authority-form" onSubmit={(event) => void submit(event)}>
              <p>The API verifies access to restricted building data. The token is held in this tab’s memory. Sessions end after 20 minutes or when you sign out.</p>
              <label>Authority token <input name="token" type="password" required autoComplete="off" spellCheck={false} /></label>
              <details><summary>Protected PMTiles archive (optional)</summary>
                <label>Archive path on the API origin <input name="archive" type="text" autoComplete="off" placeholder="/private/wards-buildings.pmtiles" /></label>
                <p>The archive server must validate the authority header and serve non-cacheable ranges.</p>
              </details>
              {error && <p role="alert">{error}</p>}
              <button type="submit" className="primary-button" disabled={pending}>{pending ? 'Verifying…' : 'Verify access'}</button>
            </form>
          )}
        </div>
      </Modal>}
    </div>
  )
}
