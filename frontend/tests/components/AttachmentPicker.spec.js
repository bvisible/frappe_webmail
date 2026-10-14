/**
 * AttachmentPicker — the Document tab (canvas « Neodesk », board 23, as Neodesk joins a document): by kind, the
 * documents of the people written to first, each with its party, amount and date; the PDF in a template and a language.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import AttachmentPicker from "@/components/AttachmentPicker.vue";

const documents = [
	{
		doctype: "Sales Invoice",
		kind: "invoice",
		label: "Sales Invoice",
		name: "FA-2026-0121",
		party: "Marc Rey",
		amount: 6000,
		currency: "CHF",
		date: "2026-10-14",
		linked: true,
	},
	{
		doctype: "Quotation",
		kind: "quotation",
		label: "Quotation",
		name: "DEV-2026-0412",
		party: "Atelier Favre",
		amount: 18600,
		currency: "CHF",
		date: "2026-10-08",
		linked: false,
	},
];

function answering() {
	frappe.call.mockImplementation(({ method }) => {
		if (method === "frappe_webmail.api.list_attachable_documents")
			return Promise.resolve({ message: documents });
		if (method === "frappe_webmail.webmail_api.get_print_formats")
			return Promise.resolve({
				message: [
					{ name: "Standard", label: "Standard" },
					{ name: "Facture Neoffice", label: "Facture Neoffice" },
				],
			});
		if (method === "frappe_webmail.webmail_api.generate_document_pdf")
			return Promise.resolve({
				message: {
					filename: "FA-2026-0121.pdf",
					content: "JVBERi0=",
					content_type: "application/pdf",
					size: 94208,
				},
			});
		return Promise.resolve({ message: [] });
	});
}

async function openDocuments() {
	const wrapper = mount(AttachmentPicker, {
		props: { show: true, account: "me@example.com", emails: ["marc.rey@example.com"] },
	});
	wrapper.vm.activeTab = "document";
	await flushPromises();
	return wrapper;
}

const calls = (method) =>
	frappe.call.mock.calls.filter((c) => c[0].method === method).map((c) => c[0].args);

describe("AttachmentPicker — a Neoffice document as a PDF", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		answering();
	});

	it("lists every kind, those of the recipients first, with their party, amount and date", async () => {
		const wrapper = await openDocuments();
		expect(calls("frappe_webmail.api.list_attachable_documents")[0]).toEqual({
			search: null,
			kind: null,
			emails: JSON.stringify(["marc.rey@example.com"]),
			limit: 30,
		});
		expect(wrapper.find(".jd-section").text()).toBe(
			"Those of the recipients first, then the most recent"
		);
		const rows = wrapper.findAll(".document-item");
		expect(rows.length).toBe(2);
		expect(rows[0].find(".doc-name").text()).toContain("FA-2026-0121");
		const meta = rows[0].find(".doc-description").text();
		expect(meta).toContain("Marc Rey");
		expect(meta).toMatch(/6.?000/);
	});

	it("asks again for one kind", async () => {
		const wrapper = await openDocuments();
		const quotations = wrapper
			.findAll(".jd-chip")
			.find((chip) => chip.text() === "Quotations");
		await quotations.trigger("click");
		await flushPromises();
		expect(calls("frappe_webmail.api.list_attachable_documents").at(-1)).toMatchObject({
			kind: "quotation",
		});
	});

	it("prints the document picked in its template and language, and gives it with its reference", async () => {
		const wrapper = await openDocuments();
		await wrapper.findAll(".document-item")[0].trigger("click");
		await flushPromises();
		expect(calls("frappe_webmail.webmail_api.get_print_formats")).toEqual([
			{ doctype: "Sales Invoice" },
		]);
		expect(wrapper.find(".jd-options select").findAll("option").length).toBe(2);
		wrapper.vm.docFormat = "Facture Neoffice";
		wrapper.vm.docLanguage = "de";
		await wrapper.vm.attachSelected();
		expect(calls("frappe_webmail.webmail_api.generate_document_pdf")[0]).toEqual({
			doctype: "Sales Invoice",
			docname: "FA-2026-0121",
			print_format: "Facture Neoffice",
			language: "de",
		});
		const given = wrapper.emitted("select")[0][0];
		expect(given).toMatchObject({
			source: "document",
			filename: "FA-2026-0121.pdf",
			doctype: "Sales Invoice",
			docname: "FA-2026-0121",
		});
	});

	it("leaves the template to the server's default when it is « Standard »", async () => {
		const wrapper = await openDocuments();
		await wrapper.findAll(".document-item")[1].trigger("click");
		await flushPromises();
		await wrapper.vm.attachSelected();
		expect(calls("frappe_webmail.webmail_api.generate_document_pdf")[0]).toMatchObject({
			doctype: "Quotation",
			docname: "DEV-2026-0412",
			print_format: null,
		});
	});
});
