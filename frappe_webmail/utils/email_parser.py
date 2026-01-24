# Copyright (c) 2024, Neoservice and contributors
# For license information, please see license.txt

"""
Email Parser Utilities

Provides utilities for parsing email messages, including MIME decoding,
HTML sanitization, and attachment extraction.
"""

import base64
import email
import re
from email.header import decode_header

import frappe
from frappe import _

try:
	import bleach
except ImportError:
	bleach = None


class EmailParser:
	"""
	Email parser for handling MIME messages.

	Provides methods for parsing email content, extracting attachments,
	and sanitizing HTML.
	"""

	# Safe HTML tags for email display
	SAFE_TAGS = [
		"a",
		"abbr",
		"acronym",
		"b",
		"blockquote",
		"br",
		"code",
		"div",
		"em",
		"h1",
		"h2",
		"h3",
		"h4",
		"h5",
		"h6",
		"hr",
		"i",
		"img",
		"li",
		"ol",
		"p",
		"pre",
		"span",
		"strong",
		"table",
		"tbody",
		"td",
		"th",
		"thead",
		"tr",
		"u",
		"ul",
	]

	SAFE_ATTRIBUTES = {
		"*": ["class", "style"],
		"a": ["href", "title", "target", "rel"],
		"img": ["src", "alt", "width", "height"],
		"table": ["border", "cellpadding", "cellspacing", "width"],
		"td": ["colspan", "rowspan", "width", "valign", "align"],
		"th": ["colspan", "rowspan", "width", "valign", "align"],
	}

	def __init__(self, raw_message):
		"""
		Initialize parser with raw email message.

		Args:
			raw_message: Raw email message bytes
		"""
		if isinstance(raw_message, bytes):
			self.message = email.message_from_bytes(raw_message)
		else:
			self.message = email.message_from_string(raw_message)

		self._html_content = None
		self._text_content = None
		self._attachments = None
		self._inline_images = None
		self._parsed = False

	def parse(self):
		"""Parse the email message and extract content"""
		if self._parsed:
			return

		self._html_content = None
		self._text_content = None
		self._attachments = []
		self._inline_images = {}

		for part in self.message.walk():
			content_type = part.get_content_type()
			content_disposition = str(part.get("Content-Disposition", ""))
			content_id = part.get("Content-ID", "").strip("<>")

			if "attachment" in content_disposition:
				self._extract_attachment(part)
			elif content_type.startswith("image/") and content_id:
				self._extract_inline_image(part, content_id)
			elif content_type == "text/html" and self._html_content is None:
				self._extract_html(part)
			elif content_type == "text/plain" and self._text_content is None:
				self._extract_text(part)

		# Replace CID references with inline data
		if self._html_content and self._inline_images:
			for cid, data_uri in self._inline_images.items():
				self._html_content = self._html_content.replace(f"cid:{cid}", data_uri)

		self._parsed = True

	def _extract_html(self, part):
		"""Extract HTML content from message part"""
		payload = part.get_payload(decode=True)
		if payload:
			charset = part.get_content_charset() or "utf-8"
			self._html_content = payload.decode(charset, errors="replace")

	def _extract_text(self, part):
		"""Extract plain text content from message part"""
		payload = part.get_payload(decode=True)
		if payload:
			charset = part.get_content_charset() or "utf-8"
			self._text_content = payload.decode(charset, errors="replace")

	def _extract_attachment(self, part):
		"""Extract attachment metadata"""
		payload = part.get_payload(decode=True)
		content_id = part.get("Content-ID", "").strip("<>")

		self._attachments.append(
			{
				"id": content_id or str(len(self._attachments)),
				"filename": self.decode_header(part.get_filename())
				or f"attachment_{len(self._attachments)}",
				"content_type": part.get_content_type(),
				"size": len(payload) if payload else 0,
				"data": payload,
			}
		)

	def _extract_inline_image(self, part, content_id):
		"""Extract inline image as data URI"""
		payload = part.get_payload(decode=True)
		if payload:
			content_type = part.get_content_type()
			self._inline_images[content_id] = (
				f"data:{content_type};base64,{base64.b64encode(payload).decode()}"
			)

	@property
	def html_content(self):
		"""Get HTML content"""
		if not self._parsed:
			self.parse()
		return self._html_content

	@property
	def text_content(self):
		"""Get plain text content"""
		if not self._parsed:
			self.parse()
		return self._text_content

	@property
	def attachments(self):
		"""Get list of attachments"""
		if not self._parsed:
			self.parse()
		return self._attachments

	@property
	def inline_images(self):
		"""Get inline images as dict of content_id -> data_uri"""
		if not self._parsed:
			self.parse()
		return self._inline_images

	def get_sanitized_html(self, block_external_images=True):
		"""
		Get sanitized HTML content safe for display.

		Args:
			block_external_images: Whether to block external image URLs

		Returns:
			str: Sanitized HTML content
		"""
		if not self._parsed:
			self.parse()

		content = self._html_content
		if not content:
			if self._text_content:
				# Convert plain text to HTML
				content = self._text_to_html(self._text_content)
			else:
				return ""

		# Block external images if requested
		if block_external_images:
			content = self._block_external_images(content)

		# Sanitize with bleach if available
		if bleach:
			content = bleach.clean(
				content, tags=self.SAFE_TAGS, attributes=self.SAFE_ATTRIBUTES, strip=True
			)
		else:
			# Basic sanitization without bleach
			content = self._basic_sanitize(content)

		return content

	def _text_to_html(self, text):
		"""Convert plain text to HTML"""
		if not text:
			return ""

		# Escape HTML entities
		text = text.replace("&", "&amp;")
		text = text.replace("<", "&lt;")
		text = text.replace(">", "&gt;")
		text = text.replace("\n", "<br>")

		return f'<pre style="white-space: pre-wrap; font-family: inherit;">{text}</pre>'

	def _block_external_images(self, html):
		"""Replace external image sources with placeholder"""
		# Match img tags with http/https src
		pattern = r'(<img[^>]*src=")https?://([^"]+)(")'
		replacement = r'\1data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><text y="15" fill="gray" font-size="12">[Image bloquée]</text></svg>\3'
		return re.sub(pattern, replacement, html, flags=re.IGNORECASE)

	def _basic_sanitize(self, html):
		"""Basic HTML sanitization without bleach"""
		# Remove script and style tags
		html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
		html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.IGNORECASE | re.DOTALL)

		# Remove event handlers
		html = re.sub(r'\s+on\w+="[^"]*"', "", html, flags=re.IGNORECASE)
		html = re.sub(r"\s+on\w+='[^']*'", "", html, flags=re.IGNORECASE)

		return html

	@staticmethod
	def decode_header(header):
		"""
		Decode MIME encoded header.

		Args:
			header: Raw header value

		Returns:
			str: Decoded header value
		"""
		if not header:
			return ""
		if isinstance(header, bytes):
			header = header.decode("utf-8", errors="replace")

		try:
			decoded_parts = decode_header(header)
			result = []
			for part, charset in decoded_parts:
				if isinstance(part, bytes):
					result.append(part.decode(charset or "utf-8", errors="replace"))
				else:
					result.append(part)
			return "".join(result)
		except Exception:
			return str(header)

	@staticmethod
	def format_address(addr):
		"""
		Format email address from IMAP envelope.

		Args:
			addr: IMAP envelope address object

		Returns:
			str: Formatted email address
		"""
		if not addr:
			return ""
		try:
			mailbox = addr.mailbox.decode() if isinstance(addr.mailbox, bytes) else addr.mailbox
			host = addr.host.decode() if isinstance(addr.host, bytes) else addr.host
			return f"{mailbox}@{host}"
		except Exception:
			return ""

	@staticmethod
	def has_attachments(bodystructure):
		"""
		Check if email has attachments from BODYSTRUCTURE.

		Args:
			bodystructure: IMAP BODYSTRUCTURE response

		Returns:
			bool: True if message has attachments
		"""
		if not bodystructure:
			return False

		def check_part(part):
			if isinstance(part, tuple):
				if len(part) >= 2:
					for item in part:
						if isinstance(item, tuple) and len(item) >= 2:
							if (
								item[0]
								and isinstance(item[0], bytes)
								and item[0].lower() == b"attachment"
							):
								return True
						if isinstance(item, tuple):
							if check_part(item):
								return True
			return False

		return check_part(bodystructure)
