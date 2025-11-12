frappe.ui.form.on("Sales Order", {
	refresh: function (frm) {
		if (frm.doc.docstatus == 1) {
			frm.add_custom_button(
				__("Initiate KCB STK Push"),
				function (params) {
					frappe.msgprint("Initiating KCB STK Push");
				},
				__("Create")
			);
		}
	},
});
