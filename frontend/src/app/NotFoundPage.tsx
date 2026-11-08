import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-muted-foreground">This page doesn’t exist yet.</p>
      <Link to="/" className="mt-6 inline-block text-sm underline underline-offset-4">
        Back to status
      </Link>
    </div>
  )
}
