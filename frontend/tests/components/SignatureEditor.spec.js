/**
 * SignatureEditor — what a person may take out of the company signature that applies to them: their photo (shown only
 * if they say yes) and their mobile number. Their own choices only: the method names nobody else.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import SignatureEditor from "@/components/SignatureEditor.vue";

const CHOICES = {
	template: true,
	photo: true,
	mobile: true,
	photo_allowed: 0,
	hide_mobile: 0,
	photo_url: "",
	photo_state: "off",
};

function answering(choices, saved) {
	frappe.call.mockImplementation(async ({ method, args }) => {
		if (method.endsWith("get_signatures")) return { message: [] };
		if (method === "frappe_webmail.signatures.save_my_choices") {
			if (saved instanceof Error) throw saved;
			return { message: { ...choices, ...saved(args) } };
		}
		if (method === "frappe_webmail.signatures.my_choices") return { message: choices };
		return { message: {} };
	});
}

async function mounted() {
	const wrapper = mount(SignatureEditor);
	await flushPromises();
	return wrapper;
}

describe("SignatureEditor, the company signature's choices", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("shows nothing to choose when no company signature with a photo or a mobile applies", async () => {
		for (const choices of [
			{ ...CHOICES, template: false, photo: false, mobile: false },
			{ ...CHOICES, photo: false, mobile: false },
		]) {
			answering(choices, () => ({}));
			const wrapper = await mounted();
			expect(wrapper.find(".company-choices").exists()).toBe(false);
			wrapper.unmount();
		}
	});

	it("offers only what the template shows", async () => {
		answering({ ...CHOICES, photo: false }, () => ({}));
		const wrapper = await mounted();
		const labels = wrapper.findAll(".choice").map((choice) => choice.text());
		expect(labels).toEqual(["Hide my mobile number"]);
	});

	it("saves the photo choice as the person's own, then has the composer take the signature again", async () => {
		answering(CHOICES, (args) => ({
			photo_allowed: args.photo_allowed,
			photo_url: "/private/files/signature-photo-0123456789.jpg",
			photo_state: "ready",
		}));
		const wrapper = await mounted();
		const box = wrapper.findAll(".choice input")[0];
		expect(box.element.checked).toBe(false);
		box.element.checked = true;
		await box.trigger("change");
		await flushPromises();

		const saved = frappe.call.mock.calls.find(([options]) =>
			options.method.endsWith("save_my_choices")
		)[0];
		expect(saved.method).toBe("frappe_webmail.signatures.save_my_choices");
		expect(saved.args).toEqual({ photo_allowed: 1 });
		expect(wrapper.emitted("updated")).toBeTruthy();
		// The copy that messages carry, shown to the person
		expect(wrapper.find(".choice-photo img").attributes("src")).toBe(
			"/private/files/signature-photo-0123456789.jpg"
		);
	});

	it("says why no photo is shown", async () => {
		answering({ ...CHOICES, photo_allowed: 1, photo_state: "missing" }, () => ({}));
		const wrapper = await mounted();
		expect(wrapper.find(".choice-photo").text()).toBe(
			"No photo of you was found: add one in My Settings."
		);
	});

	it("shows what is saved when saving fails", async () => {
		answering(CHOICES, new Error("refused"));
		const wrapper = await mounted();
		const box = wrapper.findAll(".choice input")[1];
		box.element.checked = true;
		await box.trigger("change");
		await flushPromises();
		expect(box.element.checked).toBe(false);
		expect(frappe.toast).toHaveBeenCalledWith(
			expect.objectContaining({
				message: "Your choice could not be saved",
				indicator: "red",
			})
		);
		expect(wrapper.emitted("updated")).toBeFalsy();
	});
});
