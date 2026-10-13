# The webmail on a bench

The real Vue code of the webmail, mounted alone, with invented mailboxes (`fixtures.js`) and the desk's real theme
(loaded from an instance). For looking at the screen and comparing it with the design boards without opening
anyone's mailbox, and for trying a change before it reaches an instance.

```sh
cd frontend && npx vite --config harness/vite.config.js   # http://127.0.0.1:5199/
```

- `?theme=dark` the dark theme, `?lang=en` the English strings (the msgids), `?slow=1500` slow answers.
- `frappe.call` answers from `harness.js` (`answers`, by the method's last name) after a short delay; every call is
  logged in the console as `[harness] <method> <args>`, and a method the bench does not know says so.
- `__()` translates with the app's own `frappe_webmail/locale/fr.po`.

It proves the look and the flow on screen, not the server: the server's behaviour is proven by its tests
(`frappe_webmail/tests`), and the whole by a trial on an instance.
