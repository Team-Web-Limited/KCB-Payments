import frappe


def clean_kcb_auth():
	if (
		frappe.request.path
		== "/api/method/kcb_payments.kcb_payments.utils.kcb_payment_notification.kcb_payment_notification"
	):
		if frappe.request.headers.get("Authorization"):
			frappe.log_error("KCB Request headers", str(frappe.request.headers))
			# del frappe.request.headers["Authorization"]
