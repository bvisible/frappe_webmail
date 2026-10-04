# Copyright (c) 2026, Neoservice and contributors
# For license information, please see license.txt

"""Translation anchors: strings that `bench generate-pot-file` cannot see on its own.

The extractor reads DocType JSON files WITHOUT a context, so a Select option such as
"move" in Email Filter lands in the POT as the bare key. The bare key is shared by the
whole site (frappe and suite translate "move" as an icon name), and the desk form looks
the option up as "move:Email Filter" first. The contextual entry in `locale/fr.po` only
survives `bench update-po-files` if the POT also carries it, which is what this module is for.

This function is never called: it exists so the extractor finds the strings.
"""

from frappe import _


def _i18n_anchors():
	"""Never called. See the module docstring."""
	_("move", context="Email Filter")
