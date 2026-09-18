import React, { useEffect } from 'react'
import ReactDOM from 'react-dom/client'
import { ClerkProvider, UserButton, useAuth, useClerk, useUser } from '@clerk/react'
import App from './App.jsx'
import LandingPage from './components/LandingPage.jsx'
import { setTokenGetter } from './api'
import './App.css'
import './excel-theme.css'
import './landing.css'

const CLERK_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

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

  if (!isLoaded) return <div className="boot">Loading…</div>

  if (!isSignedIn) {
    const signIn = () => clerk.openSignIn()
    const signUp = () => clerk.openSignUp()
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

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {CLERK_KEY ? (
      <ClerkProvider publishableKey={CLERK_KEY}>
        <Root />
      </ClerkProvider>
    ) : (
      <App />
    )}
  </React.StrictMode>,
)
