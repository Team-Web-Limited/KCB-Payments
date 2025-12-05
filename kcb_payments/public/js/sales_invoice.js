frappe.ui.form.on("Sales Invoice", {
	refresh: function (frm) {
		add_payment_reconciliation_button(frm);
	},
});

const add_payment_reconciliation_button = (frm) => {
	if (frm.doc.docstatus === 1 && !frm.doc.is_return && frm.doc.outstanding_amount > 0) {
		frm.add_custom_button(__("Get KCB Payments"), () => {
			show_dialog(frm);
		});
	}
};

const show_dialog = (frm) => {
	let d = new frappe.ui.Dialog({
		title: __(`KCB Payment Transaction Search`),
		fields: [
			{
				fieldtype: "Data",
				label: __("Customer Name"),
				fieldname: "customer_name",
				placeholder: __("Enter Customer name..."),
				reqd: 0,
			},
			{
				fieldtype: "Data",
				label: __("Phone Number"),
				fieldname: "phone_number",
				placeholder: __("Enter phone number, e.g. 2547XXXXXXXX..."),
				reqd: 0,
			},
			{
				fieldtype: "Int",
				label: __("Amount"),
				fieldname: "amount",
				placeholder: __("Enter amount..."),
				reqd: 0,
			},
			{
				fieldtype: "Data",
				label: __("Mpesa Transaction ID"),
				fieldname: "mpesa_transaction_id",
				placeholder: __("Enter Mpesa Transaction ID..."),
				reqd: 0,
			},
		],
		primary_action_label: __("Fetch Payments"),
		primary_action: function (values) {
			if (
				!values.customer_name &&
				!values.phone_number &&
				!values.amount &&
				!values.mpesa_transaction_id
			) {
				frappe.msgprint({
					title: __("Validation Error"),
					message: __("Please enter at least one search criteria."),
					indicator: "red",
				});
				return;
			}

			// Search for transactions based on input criteria
			searchKCBPayments(values, frm);

			d.hide();
		},
		secondary_action_label: __("Close"),
		secondary_action: function () {
			d.hide();
		},
	});

	d.show();
};

const searchKCBPayments = (searchCriteria, frm) => {
	frappe.call({
		method: "kcb_payments.kcb_payments.utils.kcb_payment_notification.fetch_kcb_payment_transactions",
		args: {
			phone_number: searchCriteria.phone_number,
			name: searchCriteria.customer_name,
			amount: searchCriteria.amount,
			originator_conversation_id: searchCriteria.mpesa_transaction_id,
		},
		callback: function (response) {
			if (response.message && response.message.length > 0) {
				display_kcb_payment_transactions_results(response.message, frm);
			} else {
				frappe.msgprint({
					title: __("No Results"),
					message: __("No matching payments found for the given criteria."),
					indicator: "orange",
				});
			}
		},
	});
};

const display_kcb_payment_transactions_results = (transactions, frm) => {
	let results_dialog = new frappe.ui.Dialog({
		title: __("KCB Payment Transactions"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "results_html",
				options: create_kcb_transactions_HTML(transactions),
			},
		],
		primary_action_label: __("Close"),
		primary_action: function () {
			results_dialog.hide();
		},
	});

	results_dialog.show();

	$(results_dialog.wrapper).on("click", ".select-transaction", function () {
		let transaction_id = $(this).data("transaction-id");
		frappe.call({
			method: "kcb_payments.kcb_payments.utils.kcb_payment_notification.process_kcb_payment",
			args: {
				payment: transaction_id,
				sales_invoice: frm.doc.name,
			},
			callback: function (response) {
				if (!response.exc) {
					frappe.msgprint({
						title: __("Success"),
						message: __("Payment reconciled successfully."),
						indicator: "green",
					});
					frm.reload_doc();
					results_dialog.hide();
				}
			},
			error: function (error) {
				frappe.msgprint({
					title: __("Error"),
					message:
						error.message || __("An error occurred while reconciling the payment."),
					indicator: "red",
				});
			},
		});
	});
};

const create_kcb_transactions_HTML = (transactions) => {
	let html = '<div class="kcb-payments-search-results">';
	html +=
		'<p class="text-muted">' +
		__("Select a transaction to proceed with reconciliation:") +
		"</p>";
	html += '<table class="table table-bordered table-hover">';
	html += "<thead><tr>";
	html += "<th>" + __("ID") + "</th>";
	html += "<th>" + __("Mobile No.") + "</th>";
	html += "<th>" + __("Customer") + "</th>";
	html += "<th>" + __("Amount") + "</th>";
	html += "<th>" + __("Mpesa ID") + "</th>";
	html += "<th>" + __("Action") + "</th>";
	html += "</tr></thead><tbody>";

	if (transactions && transactions.length > 0) {
		transactions.forEach((transaction) => {
			html += "<tr>";
			html += "<td>" + transaction.name + "</td>";
			html += "<td>" + transaction.mobile_number + "</td>";
			html += "<td>" + transaction.first_name + " " + transaction.last_name + "</td>";
			html += "<td>" + transaction.amount + "</td>";
			html += "<td>" + transaction.originator_conversation_id + "</td>";
			html +=
				'<td><button class="btn btn-xs btn-primary select-transaction" data-transaction-id="' +
				transaction.name +
				'">' +
				__("Reconcile") +
				"</button></td>";
			html += "</tr>";
		});
	} else {
		html +=
			'<tr><td colspan="6" class="text-center">' +
			__("No transactions found.") +
			"</td></tr>";
	}

	html += "</tbody></table></div>";
	return html;
};
