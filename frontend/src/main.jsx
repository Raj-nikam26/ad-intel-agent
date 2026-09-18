import React, { Suspense, lazy, useEffect } from 'react'
import ReactDOM from 'react-dom/client'
import { ClerkProvider, UserButton, useAuth, useClerk, useUser } from '@clerk/react'
import LandingPage from './components/LandingPage.jsx'
import CookieNotice from './components/CookieNotice.jsx'
import { setTokenGetter } from './api'
import './App.css'
import './excel-theme.css'
import './landing.css'
import './workspace.css'

// The workspace and the secondary pages load on demand, so the landing
// page downloads only what it shows.
const App = lazy(() => import('./App.jsx'))
const LegalPage = lazy(() => import('./components/LegalPage.jsx'))
const NotFound = lazy(() => import('./components/NotFound.jsx'))

const CLERK_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY
const Boot = () => <div className="boot" role="status">Loading…</div>

/**
 * With a Clerk key configured:
 *   signed out -> the public landing page; Sign in / Get started open
 *                 Clerk's modal, and so does trying to open a file
 *   signed in  -> the app, with every API call carrying the session token
 * Without a key the app runs open - the demo mode, matching
 * AUTH_ENABLED=false on the server.
 */
function Root() {
  const { isLoaded, isSignedIn, getToken } = useAuth()
  const { user } = useUser()
  const clerk = useClerk()

  useEffect(() => {
    // getToken returns a fresh short-lived token, refreshing it as needed.
    setTokenGetter(isSignedIn ? () => getToken() : null)
  }, [isSignedIn, getToken])

  // Most visitors are signed out, so the landing page renders at once
  // instead of waiting for the sign-in script; buttons work once it loads.
  if (!isLoaded || !isSignedIn) {
    const signIn = () => { if (clerk.loaded) clerk.openSignIn() }
    const signUp = () => { if (clerk.loaded) clerk.openSignUp() }
    return (
      <LandingPage
        onSignIn={signIn}
        onSignUp={signUp}
        onUpload={signIn}
        onSample={signIn}
        uploading={false}
        error={null}
      />
    )
  }

  const account = {
    name: user?.fullName || user?.firstName || user?.primaryEmailAddress?.emailAddress || 'Signed in',
    email: user?.primaryEmailAddress?.emailAddress || '',
    button: <UserButton />,
  }
  return <App account={account} />
}

function Page() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  if (path === '/privacy' || path === '/terms') return <LegalPage kind={path.slice(1)} />
  if (path !== '/') return <NotFound />
  return CLERK_KEY ? <Root /> : <App />
}

const tree = (
  <Suspense fallback={<Boot />}>
    <Page />
    <CookieNotice />
  </Suspense>
)

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {CLERK_KEY ? <ClerkProvider publishableKey={CLERK_KEY}>{tree}</ClerkProvider> : tree}
  </React.StrictMode>,
)
