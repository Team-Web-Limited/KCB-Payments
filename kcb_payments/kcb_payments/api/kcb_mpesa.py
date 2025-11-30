import json
import time
import uuid

import frappe
import requests
from frappe import _


@frappe.whitelist()
def generate_stk_push(**args) -> any:
	# If args is a single key "args" containing a JSON string, parse it
	if len(args) == 1 and "args" in args:
		try:
			parsed_args = json.loads(args.get("args"))
			if isinstance(parsed_args, dict):
				args = frappe._dict(parsed_args)
			else:
				frappe.log_error(_("Invalid input format. Expected JSON object."))
		except json.JSONDecodeError:
			frappe.log_error(_("Failed to decode JSON arguments."))
	else:
		args = frappe._dict(args)

	if not args.get("callback_url"):
		from ..utils.utils import get_stk_push_callback

		args["callback_url"] = get_stk_push_callback()
		frappe.log_error("Callback URL", f"\nCallback URL: {args['callback_url']}\n")

	required_fields = ["payment_gateway", "phone_number", "request_amount", "callback_url"]
	missing_fields = [field for field in required_fields if not args.get(field)]

	if missing_fields:
		frappe.log_error(_("Missing required fields: {0}").format(", ".join(missing_fields)))

	settings = frappe.get_doc("KCB Mpesa Settings", args.get("settings"))
	kcb_mpesa_stk_request = frappe.get_doc("KCB Mpesa STK Request", args.get("kcb_mpesa_stk_request"))
	access_token = settings.get_access_token()

	if not access_token:
		frappe.throw("Failed to retrieve access token. Please check KCB Mpesa Settings.")

	base_url = "https://uat.buni.kcbgroup.com" if settings.sandbox else "https://api.buni.kcbgroup.com"
	url = f"{base_url}/mm/api/request/1.0.0/stkpush"

	message_id = f"{int(time.time())}_KCBOrg_{uuid.uuid4().hex[:10]}"

	headers = {
		"accept": "application/json",
		"routeCode": "207",
		"operation": "STKPush",
		"messageId": message_id,
		"Content-Type": "application/json",
		"Authorization": f"Bearer {access_token}",
	}

	payload = {
		"phoneNumber": args.get("phone_number"),
		"amount": args.get("request_amount"),
		"invoiceNumber": args.get("invoice_number"),
		"sharedShortCode": True,
		"orgShortCode": "",
		"orgPassKey": "",
		"callbackUrl": args.get("callback_url"),
		"transactionDescription": args.get("transaction_description"),
	}

	frappe.logger().info(
		{
			"event": "KCB STK Push Initiated",
			"timestamp": frappe.utils.now(),
			"message_id": message_id,
			"url": url,
			"phone_number": args.get("phone_number"),
			"payload": payload,
			"headers": {k: v for k, v in headers.items() if k != "Authorization"},
		}
	)

	try:
		response = requests.post(url, headers=headers, json=payload, timeout=10)
		response_text = response.text

		try:
			response_json = response.json()
		except ValueError:
			frappe.log_error("Invalid JSON in KCB STK Push response", response_text)
			kcb_mpesa_stk_request.status = "Failed"
			kcb_mpesa_stk_request.error_message = "Invalid JSON response"
			kcb_mpesa_stk_request.error_description = response_text
			kcb_mpesa_stk_request.save(ignore_permissions=True)
			frappe.db.commit()
			return {"status_code": response.status_code, "error": "Invalid JSON response from KCB API"}

		# Success
		if response.status_code in [200, 201] and "response" in response_json:
			resp = response_json["response"]
			if resp.get("ResponseCode") == "0":
				kcb_mpesa_stk_request.merchant_request_id = resp.get("MerchantRequestID", "")
				kcb_mpesa_stk_request.response_code = resp.get("ResponseCode", "")
				kcb_mpesa_stk_request.customer_message = resp.get("CustomerMessage", "")
				kcb_mpesa_stk_request.checkout_request_id = resp.get("CheckoutRequestID", "")
				kcb_mpesa_stk_request.response_description = resp.get("ResponseDescription", "")
				kcb_mpesa_stk_request.status = "In Progress"
				kcb_mpesa_stk_request.error_message = ""
				kcb_mpesa_stk_request.error_description = ""
			else:
				# Business-level error (still HTTP 200)
				kcb_mpesa_stk_request.status = "Failed"
				kcb_mpesa_stk_request.response_code = resp.get("ResponseCode", "")
				kcb_mpesa_stk_request.response_description = resp.get("ResponseDescription", "")
				kcb_mpesa_stk_request.customer_message = resp.get("CustomerMessage", "")
				kcb_mpesa_stk_request.error_message = "Business-level error"
				kcb_mpesa_stk_request.error_description = frappe.as_json(response_json)
				frappe.log_error("KCB STK Push Business Error", frappe.as_json(response_json))

		# Non-200 response (Invalid credentials, etc.)
		elif response.status_code >= 400:
			kcb_mpesa_stk_request.status = "Failed"
			kcb_mpesa_stk_request.response_code = response_json.get("code", "")
			kcb_mpesa_stk_request.error_message = response_json.get("message", "")
			kcb_mpesa_stk_request.error_description = response_json.get("description", response_text)
			frappe.log_error(
				title="KCB STK Push HTTP Error",
				message=f"Status: {response.status_code}, Response: {response_text}",
			)

		kcb_mpesa_stk_request.save(ignore_permissions=True)
		frappe.db.commit()

		return {"status_code": response.status_code, "response": response_json}

	except requests.exceptions.RequestException as e:
		frappe.log_error("KCB Mpesa STK Push Failed", f"Network error: {e!s}")
		kcb_mpesa_stk_request.status = "Failed"
		kcb_mpesa_stk_request.error_message = "Network error"
		kcb_mpesa_stk_request.error_description = str(e)
		kcb_mpesa_stk_request.save(ignore_permissions=True)
		frappe.db.commit()
		return {"status_code": 500, "error": str(e)}

	except Exception as e:
		frappe.log_error("KCB Mpesa STK Push Failed", f"Unexpected error: {e!s}")
		kcb_mpesa_stk_request.status = "Failed"
		kcb_mpesa_stk_request.error_message = "Unexpected error"
		kcb_mpesa_stk_request.error_description = str(e)
		kcb_mpesa_stk_request.save(ignore_permissions=True)
		frappe.db.commit()
		return {"status_code": 500, "error": str(e)}
