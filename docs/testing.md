# Testing Guide

Guide pour tester Frappe Webmail.

## Structure des tests

```
frappe_webmail/
├── tests/
│   ├── __init__.py
│   ├── test_api.py           # Tests API
│   ├── test_doctypes.py      # Tests DocTypes
│   └── test_utils.py         # Tests utilitaires
frontend/
├── tests/
│   ├── setup.js              # Configuration Jest/Vitest
│   └── components/
│       ├── EmailList.spec.js
│       ├── EmailViewer.spec.js
│       └── EmailComposer.spec.js
```

## Tests Python

### Configuration

Les tests utilisent le framework de test Frappe basé sur unittest.

```python
# tests/__init__.py
# Vide ou avec des fixtures globales
```

### Lancer les tests

```bash
# Tous les tests de l'app
bench --site test.local run-tests --app frappe_webmail

# Un module spécifique
bench --site test.local run-tests \
    --app frappe_webmail \
    --module frappe_webmail.tests.test_api

# Un test spécifique
bench --site test.local run-tests \
    --app frappe_webmail \
    --module frappe_webmail.tests.test_api \
    --test test_get_accounts
```

### Écrire des tests

```python
# tests/test_api.py
import frappe
import unittest
from frappe_webmail.api import get_accounts, get_folders


class TestWebmailAPI(unittest.TestCase):
    """Tests pour l'API Webmail"""

    def setUp(self):
        """Préparation avant chaque test"""
        # Créer un utilisateur de test
        self.test_user = "test@example.com"
        if not frappe.db.exists("User", self.test_user):
            frappe.get_doc({
                "doctype": "User",
                "email": self.test_user,
                "first_name": "Test",
                "send_welcome_email": 0
            }).insert(ignore_permissions=True)

        # Créer un compte webmail de test
        self.test_account = "test@webmail.com"
        if not frappe.db.exists("Webmail Account", self.test_account):
            frappe.get_doc({
                "doctype": "Webmail Account",
                "email": self.test_account,
                "user": self.test_user,
                "imap_host": "imap.test.com",
                "imap_port": 993,
                "imap_ssl": 1,
                "imap_password": "test123",
                "smtp_host": "smtp.test.com",
                "smtp_port": 587,
                "smtp_starttls": 1,
                "smtp_password": "test123"
            }).insert(ignore_permissions=True)

        frappe.set_user(self.test_user)

    def tearDown(self):
        """Nettoyage après chaque test"""
        frappe.set_user("Administrator")

    def test_get_accounts(self):
        """Test récupération des comptes"""
        accounts = get_accounts()
        self.assertIsInstance(accounts, list)
        self.assertTrue(len(accounts) >= 1)

        account = accounts[0]
        self.assertIn("email", account)
        self.assertIn("name", account)

    def test_get_accounts_only_user_accounts(self):
        """Test que seuls les comptes de l'utilisateur sont retournés"""
        accounts = get_accounts()
        for account in accounts:
            doc = frappe.get_doc("Webmail Account", account["name"])
            self.assertEqual(doc.user, frappe.session.user)

    def test_get_folders_requires_account(self):
        """Test que get_folders nécessite un compte valide"""
        with self.assertRaises(frappe.exceptions.ValidationError):
            get_folders("invalid_account")


class TestWebmailAPIPermissions(unittest.TestCase):
    """Tests de permissions API"""

    def test_guest_cannot_access(self):
        """Test que Guest ne peut pas accéder à l'API"""
        frappe.set_user("Guest")
        with self.assertRaises(frappe.exceptions.PermissionError):
            get_accounts()

    def test_user_cannot_access_other_accounts(self):
        """Test qu'un utilisateur ne peut pas accéder aux comptes d'autres"""
        # Créer un autre utilisateur avec un compte
        other_user = "other@example.com"
        # ... setup ...

        frappe.set_user("test@example.com")
        with self.assertRaises(Exception):
            get_folders("other_user_account")
```

### Fixtures et mocking

```python
import unittest
from unittest.mock import patch, MagicMock

class TestIMAPOperations(unittest.TestCase):
    """Tests avec mock IMAP"""

    @patch('frappe_webmail.api.IMAPClient')
    def test_get_folders(self, mock_imap):
        """Test get_folders avec mock IMAP"""
        # Configuration du mock
        mock_client = MagicMock()
        mock_client.list_folders.return_value = [
            ([], b'/', 'INBOX'),
            ([b'\\Sent'], b'/', 'Sent'),
        ]
        mock_imap.return_value.__enter__.return_value = mock_client

        # Exécuter le test
        from frappe_webmail.api import get_folders
        folders = get_folders("test@example.com")

        # Vérifications
        self.assertEqual(len(folders), 2)
        self.assertEqual(folders[0]["name"], "INBOX")
        mock_client.login.assert_called_once()

    @patch('frappe_webmail.api.smtplib.SMTP')
    def test_send_email(self, mock_smtp):
        """Test send_email avec mock SMTP"""
        mock_server = MagicMock()
        mock_smtp.return_value = mock_server

        from frappe_webmail.api import send_email
        result = send_email(
            account_name="test@example.com",
            to="recipient@example.com",
            subject="Test",
            html_content="<p>Hello</p>"
        )

        self.assertTrue(result["success"])
        mock_server.sendmail.assert_called_once()
```

## Tests Frontend

### Configuration (Vitest)

```javascript
// frontend/vite.config.js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/setup.js']
  }
})
```

```javascript
// frontend/tests/setup.js
import { vi } from 'vitest'

// Mock frappe global
global.frappe = {
  call: vi.fn(),
  toast: vi.fn(),
  set_route: vi.fn(),
  session: { user: 'test@example.com' }
}
```

### Lancer les tests

```bash
cd frontend
npm test              # Tous les tests
npm test -- --watch   # Mode watch
npm test -- EmailList # Un fichier spécifique
```

### Écrire des tests

```javascript
// tests/components/EmailList.spec.js
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import EmailList from '@/components/EmailList.vue'

describe('EmailList', () => {
  beforeEach(() => {
    // Reset mocks
    vi.clearAllMocks()
  })

  it('renders empty state when no emails', async () => {
    frappe.call.mockResolvedValue({
      message: { emails: [], total: 0, has_more: false }
    })

    const wrapper = mount(EmailList, {
      props: {
        account: 'test@example.com',
        folder: 'INBOX'
      }
    })

    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Aucun email')
  })

  it('loads emails on mount', async () => {
    const mockEmails = [
      { uid: 1, subject: 'Test 1', seen: false },
      { uid: 2, subject: 'Test 2', seen: true }
    ]

    frappe.call.mockResolvedValue({
      message: { emails: mockEmails, total: 2, has_more: false }
    })

    const wrapper = mount(EmailList, {
      props: { account: 'test@example.com' }
    })

    await wrapper.vm.$nextTick()

    expect(frappe.call).toHaveBeenCalledWith({
      method: 'frappe_webmail.api.get_emails',
      args: expect.objectContaining({
        account_name: 'test@example.com',
        folder: 'INBOX'
      })
    })
  })

  it('emits select event when clicking email', async () => {
    const mockEmail = { uid: 1, subject: 'Test' }
    frappe.call.mockResolvedValue({
      message: { emails: [mockEmail], total: 1, has_more: false }
    })

    const wrapper = mount(EmailList, {
      props: { account: 'test@example.com' }
    })

    await wrapper.vm.$nextTick()
    await wrapper.find('.email-row').trigger('click')

    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')[0]).toEqual([mockEmail])
  })
})
```

```javascript
// tests/components/EmailViewer.spec.js
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import EmailViewer from '@/components/EmailViewer.vue'

describe('EmailViewer', () => {
  const mockEmail = {
    uid: 1,
    subject: 'Test Email',
    from_email: 'sender@example.com',
    from_name: 'Sender',
    to: 'recipient@example.com',
    date: '2024-01-15T10:00:00',
    html: '<p>Hello <script>alert("xss")</script></p>',
    attachments: []
  }

  it('renders email content', () => {
    const wrapper = mount(EmailViewer, {
      props: {
        email: mockEmail,
        account: 'test@example.com'
      }
    })

    expect(wrapper.text()).toContain('Test Email')
    expect(wrapper.text()).toContain('Sender')
  })

  it('sanitizes HTML content', () => {
    const wrapper = mount(EmailViewer, {
      props: {
        email: mockEmail,
        account: 'test@example.com'
      }
    })

    const iframe = wrapper.find('iframe')
    const srcdoc = iframe.attributes('srcdoc')

    // Script tags should be removed
    expect(srcdoc).not.toContain('<script>')
    expect(srcdoc).toContain('Hello')
  })

  it('blocks external images by default', () => {
    const emailWithImage = {
      ...mockEmail,
      html: '<img src="https://tracker.example.com/pixel.gif">'
    }

    const wrapper = mount(EmailViewer, {
      props: {
        email: emailWithImage,
        account: 'test@example.com'
      }
    })

    const srcdoc = wrapper.find('iframe').attributes('srcdoc')
    expect(srcdoc).not.toContain('https://tracker.example.com')
  })

  it('emits reply event', async () => {
    const wrapper = mount(EmailViewer, {
      props: {
        email: mockEmail,
        account: 'test@example.com'
      }
    })

    await wrapper.find('button:first-child').trigger('click')
    expect(wrapper.emitted('reply')).toBeTruthy()
  })
})
```

## Tests d'intégration

### Test E2E avec Cypress

```javascript
// cypress/e2e/webmail.cy.js
describe('Webmail', () => {
  beforeEach(() => {
    cy.login('test@example.com', 'password')
    cy.visit('/app/webmail')
  })

  it('loads the webmail interface', () => {
    cy.get('.webmail-container').should('exist')
    cy.get('.folder-tree').should('exist')
    cy.get('.email-list').should('exist')
  })

  it('can compose a new email', () => {
    cy.contains('Nouveau message').click()
    cy.get('.email-composer').should('be.visible')

    cy.get('input[placeholder*="destinataire"]').type('test@example.com')
    cy.get('input[placeholder*="Objet"]').type('Test Email')
    cy.get('.ProseMirror').type('Hello World')

    cy.contains('Envoyer').click()
    cy.contains('Email envoyé').should('be.visible')
  })

  it('can read an email', () => {
    cy.get('.email-row').first().click()
    cy.get('.email-viewer').should('be.visible')
    cy.get('.email-subject').should('not.be.empty')
  })
})
```

## Coverage

### Python

```bash
bench --site test.local run-tests --app frappe_webmail --coverage
```

### JavaScript

```bash
cd frontend
npm test -- --coverage
```

## CI/CD

### GitHub Actions

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  python-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Frappe
        # ... setup steps ...
      - name: Run tests
        run: bench --site test.local run-tests --app frappe_webmail

  frontend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '18'
      - run: cd frontend && npm ci
      - run: cd frontend && npm test
```

## Bonnes pratiques

1. **Isoler les tests** - Chaque test doit être indépendant
2. **Utiliser des mocks** - Ne pas dépendre de serveurs IMAP/SMTP réels
3. **Tester les cas limites** - Emails vides, attachements volumineux
4. **Tester la sécurité** - XSS, permissions
5. **Maintenir une bonne couverture** - Viser 80%+
