import json

import frappe

NCBA_ENDPOINT = (
	"/api/method/kcb_payments.kcb_payments.utils.ncba_payment_notification.ncba_payment_notification"
)

def sanitize_ncba_response(**kwargs):
	
	request = kwargs.get("request") or getattr(frappe.local, "request", None)
	response = kwargs.get("response")

	if not request or not response:
		return

	if request.path != NCBA_ENDPOINT:
		return

	# Only sanitize error responses (4xx / 5xx)
	if response.status_code < 400:
		return

	sanitized = json.dumps({
		"ResultCode": "1",
		"ResultDesc": "Request processing failed",
	})
	response.set_data(sanitized)
	response.headers["Content-Type"] = "application/json"
	# NCBA expects HTTP 200 with ResultCode indicating success/failure
	response.status_code = 200
