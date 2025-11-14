import json
import time
import uuid

import frappe
import requests
from frappe import _

from ..utils.utils import log_and_throw_error


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

	required_fields = ["payment_gateway", "phone_number", "request_amount"]
	missing_fields = [field for field in required_fields if not args.get(field)]

	if missing_fields:
		frappe.log_error(_("Missing required fields: {0}").format(", ".join(missing_fields)))

	settings = frappe.get_doc("KCB Mpesa Settings", args.get("settings"))
	kcb_mpesa_stk_request = frappe.get_doc("KCB Mpesa STK Request", args.get("kcb_mpesa_stk_request"))
	access_token = settings.get_access_token()

	if not access_token:
		frappe.throw("Failed to retrieve access token. Please check KCB Mpesa Settings.")

	url = "https://uat.buni.kcbgroup.com/mm/api/request/1.0.0/stkpush" if settings.sandbox else ""

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

	# TODO: remove this later
	# frappe.log_error(title="Payload", message=f"{payload!s}")

	try:
		response = requests.post(url, headers=headers, json=payload, timeout=10)
		response_text = response.text

		try:
			response_json = response.json()
			# TODO: remove this later
			# frappe.log_error(title="Sucessfull Response", message=f"{response_json!s}")
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


def handle_successful_transaction(request_doc, metadata_dict, settings, checkout_request_id):
	"""Handle actions for a successful transaction"""
	if request_doc.reference_doctype == "Payment Request":
		payment_request = frappe.get_doc("Payment Request", request_doc.reference_name)
		if payment_request.reference_doctype == "Sales Invoice":
			invoice = frappe.get_doc("Sales Invoice", payment_request.reference_name)
			if invoice.docstatus == 0:
				try:
					invoice.submit()
				except Exception:
					log_and_throw_error("Payment Request Submission Error", checkout_request_id)
		try:
			payment_request.create_payment_entry()
		except Exception:
			log_and_throw_error("Payment Entry Creation Error", checkout_request_id)

		try:
			if settings.auto_create_sales_invoice and payment_request.reference_doctype == "Sales Order":
				from erpnext.selling.doctype.sales_order.sales_order import (
					make_sales_invoice,
				)

				si = make_sales_invoice(payment_request.reference_name, ignore_permissions=True)
				si.allocate_advances_automatically = True
				si = si.insert(ignore_permissions=True)
				si.submit()
		except Exception:
			log_and_throw_error("Sales Invoice Creation Error", checkout_request_id)

		frappe.db.set_value("Payment Request", payment_request.name, "status", "Paid")

	elif request_doc.reference_doctype == "Sales Invoice":
		sales_invoice = frappe.get_doc("Sales Invoice", request_doc.reference_name)
		if sales_invoice.docstatus == 0:
			try:
				sales_invoice.submit()
			except Exception:
				log_and_throw_error("Sales Invoice Submission Error", checkout_request_id)
		try:
			payment_row = sales_invoice.append("payments", {})
			payment_row.amount = float(metadata_dict.get("Amount", 0))
			payment_row.mode_of_payment = request_doc.payment_gateway
			payment_row.reference_no = metadata_dict.get("MpesaReceiptNumber")
			payment_row.clearance_date = frappe.utils.nowdate()
			sales_invoice.save(ignore_permissions=True)
		except Exception:
			log_and_throw_error("Payment Creation Error", checkout_request_id)

	elif request_doc.reference_doctype == "Sales Invoice Payment":
		try:
			frappe.db.set_value(
				"Sales Invoice Payment",
				request_doc.reference_name,
				{
					"reference_no": metadata_dict.get("MpesaReceiptNumber"),
				},
			)
		except Exception:
			log_and_throw_error("Sales Invoice Payment Update Error", checkout_request_id)
