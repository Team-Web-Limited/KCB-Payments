// Copyright (c) 2025, Team Web Africa and contributors
// For license information, please see license.txt

frappe.ui.form.on("KCB Mpesa STK Request", {
	refresh(frm) {
		if (frm.doc.status == "Failed") {
			frm.add_custom_button(__("Retry STK Push"), function () {
				frappe.call({
					method: "kcb_payments.kcb_payments.api.kcb_mpesa.generate_stk_push",
					args: {
						phone_number: frm.doc.phone_number,
						request_amount: frm.doc.amount,
						invoice_number: `${frm.doc.till_no}-${frm.doc.reference_name}`,
						transaction_description: frm.doc.transaction_desc,
						payment_gateway: frm.doc.payment_gateway,
						settings: frm.doc.kcb_mpesa_settings,
						kcb_mpesa_stk_request: frm.doc.name,
					},
					freeze: true,
					freeze_message: __("Retrying STK Push..."),
					callback: function (response) {
						if (response.message) {
							if ([200, 201].includes(response.message.status_code)) {
								frappe.msgprint(
									__("Please check your phone to complete the payment.")
								);
							} else {
								console.log(response.message.response);
								frappe.msgprint(
									__("STK Push failed: Check error log for details.")
								);
							}
						}
					},
				});
			});
		}
	},
});
