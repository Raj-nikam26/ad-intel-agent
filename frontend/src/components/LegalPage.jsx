import { useEffect } from 'react'
import { ArrowLeft, FileSpreadsheet } from 'lucide-react'
import SiteFooter from './SiteFooter'
import { CONTACT_EMAIL, LEGAL_UPDATED, SITE_NAME } from '../site'

const contact = CONTACT_EMAIL
  ? <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
  : 'the contact address shown in the site footer'

function Privacy() {
  return (
    <>
      <h1>Privacy policy</h1>
      <p className="lg-updated">Last updated {LEGAL_UPDATED}</p>
      <p>
        This policy explains what {SITE_NAME} collects when you use it, why, where it is kept and the
        choices you have. {SITE_NAME} is a tool for checking and editing spreadsheets; it does not sell
        personal data or use it for advertising.
      </p>

      <h2>What we collect</h2>
      <ul>
        <li><strong>Account details.</strong> When you sign in, our sign-in provider shares your account
          identifier and, depending on how you sign in, your name, email address and profile picture.</li>
        <li><strong>Files you open.</strong> The contents of each spreadsheet you upload, every version
          created from it, and a record of each change (what changed, why, and when).</li>
        <li><strong>Assistant conversations.</strong> The messages you send to the assistant and its replies,
          so a conversation is still there when you return.</li>
        <li><strong>Technical data.</strong> Your IP address and request details, used to keep the service
          secure, to apply fair-usage limits and to diagnose errors.</li>
      </ul>

      <h2>How we use it</h2>
      <ul>
        <li>To provide the service: show your files, answer questions and apply the changes you ask for.</li>
        <li>To keep your files private to your account.</li>
        <li>To prevent abuse, including limiting how many requests one account or address can make.</li>
        <li>To fix problems and improve reliability.</li>
      </ul>

      <h2>Service providers</h2>
      <p>We rely on a small number of providers who process data on our behalf, only to run the service:</p>
      <ul>
        <li><strong>Clerk</strong> — sign-in and account management.</li>
        <li><strong>Supabase</strong> — database and file storage for your spreadsheets and their versions.</li>
        <li><strong>Neo4j Aura</strong> — the knowledge graph built from your spreadsheet’s rows.</li>
        <li><strong>OpenRouter</strong> and the language-model provider it routes to — when you message the
          assistant, your message and the relevant parts of your spreadsheet are sent to generate a reply.</li>
        <li><strong>Render</strong> and <strong>Vercel</strong> — hosting for the application.</li>
      </ul>
      <p>Some of these providers may process data outside your country.</p>

      <h2>Cookies and local storage</h2>
      <p>
        We use only what is needed for the site to work. Our sign-in provider sets cookies that keep you
        signed in. Your browser’s local storage remembers the file you last opened and that you have seen
        our cookie notice. We do not use advertising or analytics cookies.
      </p>

      <h2>How long we keep data</h2>
      <p>
        Your files, versions, change history and conversations are kept while your account is active so
        you can return to them. You can ask us to delete them, or your account, at any time.
      </p>

      <h2>Security</h2>
      <p>
        All traffic is encrypted with HTTPS. Each file is tied to the account that opened it and cannot be
        loaded by anyone else. Stored versions are signed so any tampering is detected before they are used.
        No system is perfectly secure, but we work to protect your data.
      </p>

      <h2>Your choices and rights</h2>
      <p>
        You can ask to access, correct, export or delete your personal data. Depending on where you live
        you may have further rights under laws such as the GDPR or India’s Digital Personal Data Protection
        Act. Contact us at {contact} and we will respond within a reasonable time.
      </p>

      <h2>Children</h2>
      <p>{SITE_NAME} is not intended for children under 16, and we do not knowingly collect their data.</p>

      <h2>Changes to this policy</h2>
      <p>If we change this policy, we will update the date above. Significant changes will be highlighted on the site.</p>
    </>
  )
}

function Terms() {
  return (
    <>
      <h1>Terms of service</h1>
      <p className="lg-updated">Last updated {LEGAL_UPDATED}</p>
      <p>
        These terms govern your use of {SITE_NAME}. By creating an account or using the service you agree
        to them. If you do not agree, please do not use the service.
      </p>

      <h2>The service</h2>
      <p>
        {SITE_NAME} lets you open spreadsheets, review data-quality problems, ask questions about the data
        and make changes with the help of an assistant. Features may change, and the service may be
        unavailable at times for maintenance or reasons outside our control.
      </p>

      <h2>Your account</h2>
      <p>
        You are responsible for activity under your account and for keeping your sign-in details secure.
        Tell us promptly if you believe your account has been used without permission.
      </p>

      <h2>Your content</h2>
      <p>
        You keep all rights to the files you upload. You give us permission to store, process and display
        them only as needed to provide the service to you, including sending relevant parts to the
        providers listed in our <a href="/privacy">privacy policy</a>. You must have the right to upload
        any file you use, and it must not contain data you are not permitted to share.
      </p>

      <h2>Acceptable use</h2>
      <p>You agree not to:</p>
      <ul>
        <li>break the law, or upload content that infringes others’ rights;</li>
        <li>attempt to access other users’ data or bypass security or usage limits;</li>
        <li>overload, disrupt or reverse-engineer the service, or use automated means to abuse it;</li>
        <li>upload malicious files or content.</li>
      </ul>
      <p>We may suspend or close accounts that break these rules.</p>

      <h2>Assistant answers</h2>
      <p>
        Answers and suggested changes are generated automatically and can be wrong. Review results before
        relying on them, particularly for financial, legal or other important decisions. Every change is
        saved as a version so you can compare and undo it.
      </p>

      <h2>Usage limits</h2>
      <p>To keep the service fair and available, we limit how many messages and files can be processed in a given period.</p>

      <h2>Disclaimer</h2>
      <p>
        The service is provided “as is” and “as available”, without warranties of any kind, to the fullest
        extent permitted by law. Keep your own copies of important files.
      </p>

      <h2>Limitation of liability</h2>
      <p>
        To the fullest extent permitted by law, we are not liable for any indirect, incidental or
        consequential loss, or for loss of data, profits or business, arising from your use of the service.
      </p>

      <h2>Ending your use</h2>
      <p>You may stop using the service at any time and ask us to delete your data. We may end or suspend access if these terms are broken.</p>

      <h2>Changes</h2>
      <p>We may update these terms. The date above shows the latest version. Continuing to use the service after a change means you accept the updated terms.</p>

      <h2>Contact</h2>
      <p>Questions about these terms can be sent to {contact}.</p>
    </>
  )
}

export default function LegalPage({ kind }) {
  const isPrivacy = kind === 'privacy'
  useEffect(() => {
    document.title = `${isPrivacy ? 'Privacy policy' : 'Terms of service'} — ${SITE_NAME}`
    window.scrollTo(0, 0)
  }, [isPrivacy])

  return (
    <div className="lp lg">
      <header className="lp-nav is-scrolled">
        <div className="lp-nav-inner">
          <a className="lp-brand" href="/" aria-label={`${SITE_NAME} home`}>
            <span className="lp-logo"><FileSpreadsheet size={16} strokeWidth={2.2} /></span>
            {SITE_NAME}
          </a>
          <a className="lp-link-btn lg-back" href="/"><ArrowLeft size={15} /> Back to home</a>
        </div>
      </header>
      <main className="lp-wrap lg-body" id="main">
        <article className="lg-article">{isPrivacy ? <Privacy /> : <Terms />}</article>
      </main>
      <SiteFooter />
    </div>
  )
}
