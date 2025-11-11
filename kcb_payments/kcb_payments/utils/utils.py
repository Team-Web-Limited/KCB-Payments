import json

import frappe


@frappe.whitelist(allow_guest=True, methods=["POST"])
def stk_push_callback():
	try:
		# Read and parse request body
		data = frappe.request.data
		if not data:
			frappe.log_error("KCB STK Callback Error", "Empty request body received")
			return {"status": "failed", "reason": "Empty request body"}

		try:
			payload = json.loads(data)
		except ValueError:
			frappe.log_error("KCB STK Callback Error", f"Invalid JSON: {data}")
			return {"status": "failed", "reason": "Invalid JSON payload"}

		# Extract the core callback object
		stk_callback = payload.get("Body", {}).get("stkCallback", {}) if isinstance(payload, dict) else {}

		if not stk_callback:
			frappe.log_error("KCB STK Callback Error", f"Missing stkCallback: {payload}")
			return {"status": "failed", "reason": "Missing stkCallback in payload"}

		merchant_request_id = stk_callback.get("MerchantRequestID")
		checkout_request_id = stk_callback.get("CheckoutRequestID")
		result_code = stk_callback.get("ResultCode")
		result_desc = stk_callback.get("ResultDesc")

		stk_request = None
		if merchant_request_id:
			stk_request = frappe.db.get_value(
				"KCB Mpesa STK Request",
				{"merchant_request_id": merchant_request_id},
				"name",
			)
		if not stk_request and checkout_request_id:
			stk_request = frappe.db.get_value(
				"KCB Mpesa STK Request",
				{"checkout_request_id": checkout_request_id},
				"name",
			)

		if not stk_request:
			frappe.log_error(
				"KCB STK Callback Error",
				f"No STK Request found for MerchantRequestID={merchant_request_id} or CheckoutRequestID={checkout_request_id}",
			)
			return {"status": "failed", "reason": "STK Request not found"}

		doc = frappe.get_doc("KCB Mpesa STK Request", stk_request)

		# Update the document with callback info
		doc.result_code = result_code
		doc.result_desc = result_desc
		doc.callback_received_at = frappe.utils.now()
		# doc.raw_callback = json.dumps(payload, indent=2)

		# Extract success transaction metadata
		if result_code == 0:
			metadata = stk_callback.get("CallbackMetadata", {}).get("Item", [])
			metadata_dict = {item.get("Name"): item.get("Value") for item in metadata if "Name" in item}

			doc.transaction_amount = metadata_dict.get("Amount")
			doc.mpesa_receipt_number = metadata_dict.get("MpesaReceiptNumber")
			doc.transaction_date = metadata_dict.get("TransactionDate")
			doc.callback_phone_number = metadata_dict.get("PhoneNumber")
			doc.status = "Completed"
		else:
			# Error / Failed transaction
			doc.status = "Failed"

		doc.save(ignore_permissions=True)
		frappe.db.commit()

		frappe.logger().info(
			{
				"event": "KCB STK Callback Processed",
				"merchant_request_id": merchant_request_id,
				"checkout_request_id": checkout_request_id,
				"result_code": result_code,
				"result_description": result_desc,
			}
		)

		return {"status": "success", "message": "Callback processed"}

	except Exception as e:
		frappe.log_error("KCB STK Callback Exception", f"Error: {e!s}")
		return {"status": "failed", "reason": str(e)}


def get_stk_push_callback():
	site_url = frappe.utils.get_url()
	callback_path = "/api/method/kcb_payments.kcb_payments.utils.utils.stk_push_callback"
	return f"{site_url}{callback_path}"
