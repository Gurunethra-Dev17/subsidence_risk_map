export class AuthorityError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
  }
}

export function isUnauthorized(error: unknown) {
  return error instanceof AuthorityError && (error.status === 401 || error.status === 403)
}
