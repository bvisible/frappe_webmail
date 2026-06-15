app_name = "frappe_webmail"
app_title = "Frappe Webmail"
app_publisher = "Neoservice"
app_description = "Native webmail client for Frappe with IMAP/SMTP support"
app_email = "hello@neoservice.ai"
app_license = "mit"
app_icon = "mail"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
	{
		"name": "frappe_webmail",
		"logo": "/assets/frappe_webmail/images/webmail-icon.svg",
		"title": "Webmail",
		"route": "/app/webmail",
		"has_permission": "frappe_webmail.api.permission.has_app_permission",
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = "/assets/frappe_webmail/js/frappe_webmail.css?v=20"
app_include_js = "/assets/frappe_webmail/js/frappe_webmail.bundle.iife.js?v=20"

# include js, css files in header of web template
# web_include_css = "/assets/frappe_webmail/css/frappe_webmail.css"
# web_include_js = "/assets/frappe_webmail/js/frappe_webmail.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "frappe_webmail/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "frappe_webmail/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "frappe_webmail.utils.jinja_methods",
# 	"filters": "frappe_webmail.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "frappe_webmail.install.before_install"
# after_install = "frappe_webmail.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "frappe_webmail.uninstall.before_uninstall"
# after_uninstall = "frappe_webmail.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "frappe_webmail.utils.before_app_install"
# after_app_install = "frappe_webmail.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "frappe_webmail.utils.before_app_uninstall"
# after_app_uninstall = "frappe_webmail.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "frappe_webmail.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"Webmail Account": "frappe_webmail.frappe_webmail.doctype.webmail_account.webmail_account.get_permission_query_conditions",
}

has_permission = {
	"Webmail Account": "frappe_webmail.frappe_webmail.doctype.webmail_account.webmail_account.has_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Email Signature": {
		"before_save": "frappe_webmail.frappe_webmail.doctype.email_signature.email_signature.before_save"
	}
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"frappe_webmail.tasks.all"
# 	],
# 	"daily": [
# 		"frappe_webmail.tasks.daily"
# 	],
# 	"hourly": [
# 		"frappe_webmail.tasks.hourly"
# 	],
# 	"weekly": [
# 		"frappe_webmail.tasks.weekly"
# 	],
# 	"monthly": [
# 		"frappe_webmail.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "frappe_webmail.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "frappe_webmail.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "frappe_webmail.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["frappe_webmail.utils.before_request"]
# after_request = ["frappe_webmail.utils.after_request"]

# Job Events
# ----------
# before_job = ["frappe_webmail.utils.before_job"]
# after_job = ["frappe_webmail.utils.after_job"]

# User Data Protection
# --------------------

user_data_fields = [
	{
		"doctype": "Webmail Account",
		"filter_by": "user",
		"redact_fields": ["imap_password", "smtp_password"],
		"partial": 1,
	},
	{
		"doctype": "Email Signature",
		"filter_by": "user",
		"partial": 1,
	},
]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"frappe_webmail.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Website Route Rules
# -------------------
website_route_rules = [
	{"from_route": "/webmail", "to_route": "webmail"},
	{"from_route": "/webmail/<path:app_path>", "to_route": "webmail"},
]
