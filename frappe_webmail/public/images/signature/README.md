# The icons of a signature's contacts

`phone.png`, `mobile.png`, `website.png`, `email.png`: the small picture before each way to reach a person in a company
signature (`show_contact_icons` of an Email Signature Template, `signatures.ICONS`), drawn at 14 px from 42.

Their source is the Neoffice design system (`bvisible/neoffice-design-system`, `assets/icons/email/`, built by
`templates/email-signature/build.py` from its Streamline icons, in the clay): a change is made there and copied here.
A mail client fetches them by their address (`https://<instance>/assets/frappe_webmail/images/signature/…`).
