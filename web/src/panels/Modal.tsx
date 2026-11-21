import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export default function Modal({ title, onClose, children, className = '' }: {
  title: string
  onClose: () => void
  children: ReactNode
  className?: string
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    dialog?.showModal()
    return () => dialog?.close()
  }, [])

  return (
    <dialog ref={ref} aria-label={title} className={'workspace-dialog ' + className} onCancel={(event) => {
      event.preventDefault()
      onClose()
    }}>
      <div className="dialog-bar"><h2>{title}</h2><button type="button" className="icon-button" aria-label={'Close ' + title} onClick={onClose}><X size={17} /></button></div>
      {children}
    </dialog>
  )
}
