import base64
import json
from datetime import datetime

import frappe
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from frappe import _


@frappe.whitelist(allow_guest=True, methods=["POST"])
def kcb_payment_notification():
	frappe.set_user("Administrator")

	try:
		data = json.loads(frappe.request.data)

		if not data:
			frappe.log_error("KCB IPN: Empty request body", "KCB Payment Notification")
			return generate_response(
				message_id="unknown",
				originator_conversation_id="",
				status_code="1",
				status_message="Empty request body",
				transaction_id="",
			)

		# Check if signature verification is enabled
		enable_signature_verification = frappe.conf.get("kcb_enable_signature_verification", True)

		if enable_signature_verification:
			signature = frappe.get_request_header("signature")

			if not signature:
				frappe.log_error("KCB IPN: Missing signature header", "KCB Payment Notification")
				return generate_response(
					message_id=data.get("header", {}).get("messageID", "unknown"),
					originator_conversation_id=data.get("header", {}).get("originatorConversationID", ""),
					status_code="1",
					status_message="Missing signature header",
					transaction_id="",
				)

			if not verify_signature(json.dumps(data), signature):
				frappe.log_error("KCB IPN: Invalid signature", "KCB Payment Notification")
				return generate_response(
					message_id=data.get("header", {}).get("messageID", "unknown"),
					originator_conversation_id=data.get("header", {}).get("originatorConversationID", ""),
					status_code="1",
					status_message="Invalid signature",
					transaction_id="",
				)
		else:
			frappe.log_error(
				"KCB IPN: Signature verification is DISABLED",
				"Signature verification is DISABLED\nThis should only be used for testing!\nEnable it in production.",
			)

		# Extracting header information
		header = data.get("header", {})
		message_id = header.get("messageID")
		originator_conversation_id = header.get("originatorConversationID", "")
		channel_code = header.get("channelCode")
		timestamp = header.get("timeStamp")

		# Extracting notification data
		request_payload = data.get("requestPayload", {})
		# primary_data = request_payload.get("primaryData", {})
		notification_data = request_payload.get("additionalData", {}).get("notificationData", {})

		# Extracting transaction details
		bill_reference = notification_data.get("businessKey")
		mobile_number = notification_data.get("debitMSISDN")
		amount = notification_data.get("transactionAmt")
		transaction_date = notification_data.get("transactionDate")
		kcb_transaction_id = notification_data.get("transactionID")
		first_name = notification_data.get("firstName")
		middle_name = notification_data.get("middleName", "")
		last_name = notification_data.get("lastName", "")
		currency = notification_data.get("currency")
		narration = notification_data.get("narration", "")
		transaction_type = notification_data.get("transactionType", "")
		balance = notification_data.get("balance", "")

		# Validate required fields
		if not all([message_id, bill_reference, mobile_number, amount, kcb_transaction_id]):
			print(
				f"Required fields: [{message_id}, {bill_reference}, {mobile_number}, {amount}, {kcb_transaction_id}]"
			)
			frappe.log_error("KCB IPN: Missing required fields", "KCB Payment Notification")
			return generate_response(
				message_id=message_id,
				originator_conversation_id=originator_conversation_id,
				status_code="1",
				status_message="Missing required fields",
				transaction_id="",
			)

		if frappe.db.exists("KCB Payment Transaction", {"kcb_transaction_id": kcb_transaction_id}):
			# Get existing transaction ID
			existing_doc = frappe.db.get_value(
				"KCB Payment Transaction",
				{"kcb_transaction_id": kcb_transaction_id},
				"name",
			)

			frappe.log_error(
				f"Duplicate transaction: {kcb_transaction_id}",
				"KCB Payment Notification",
			)

			return generate_response(
				message_id=message_id,
				originator_conversation_id=originator_conversation_id,
				status_code="0",
				status_message="Duplicate transaction - already processed",
				transaction_id=existing_doc,
			)

		payment_doc = frappe.get_doc(
			{
				"doctype": "KCB Payment Transaction",
				"message_id": message_id,
				"originator_conversation_id": originator_conversation_id,
				"channel_code": channel_code,
				"timestamp": timestamp,
				"bill_reference": bill_reference,
				"mobile_number": mobile_number,
				"amount": frappe.utils.flt(amount, 2),
				"transaction_date": transaction_date,
				"kcb_transaction_id": kcb_transaction_id,
				"first_name": first_name,
				"middle_name": middle_name,
				"last_name": last_name,
				"currency": currency,
				"narration": narration,
				"transaction_type": transaction_type,
				"balance": frappe.utils.flt(balance, 2) if balance else 0.0,
				"status": "Received",
			}
		)

		payment_doc.insert(ignore_permissions=True)
		payment_doc.submit()
		frappe.db.commit()

		# Process payment
		try:
			process_payment(payment_doc)
			payment_doc.status = "Received"
			payment_doc.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception as e:
			frappe.log_error(f"Error processing payment: {e!s}", "KCB Payment Processing")
			payment_doc.status = "Failed"
			payment_doc.error_message = str(e)
			payment_doc.save(ignore_permissions=True)
			frappe.db.commit()

			return generate_response(
				message_id=message_id,
				originator_conversation_id=originator_conversation_id,
				status_code="1",
				status_message=f"Payment received but processing failed: {e!s}",
				transaction_id=payment_doc.name,
			)

		# Return success response
		return generate_response(
			message_id=message_id,
			originator_conversation_id=originator_conversation_id,
			status_code="0",
			status_message="Notification received successfully",
			transaction_id=payment_doc.name,
		)

	except Exception as e:
		frappe.log_error(
			"KCB Payment Notification",
			f"KCB IPN Error: {e!s}\n{frappe.get_traceback()}",
		)

		return generate_response(
			message_id=(data.get("header", {}).get("messageID", "unknown") if data else "unknown"),
			originator_conversation_id=(
				data.get("header", {}).get("originatorConversationID", "") if data else ""
			),
			status_code="1",
			status_message=f"Internal error: {e!s}",
			transaction_id="",
		)


def verify_signature(payload, signature):
	try:
		public_key_str = frappe.conf.get("kcb_public_key") or frappe.db.get_single_value(
			"KCB IPN Settings", "public_key"
		)

		if not public_key_str:
			frappe.log_error("KCB public key not configured", "KCB Signature Verification")
			return False

		# Load the public key
		public_key = serialization.load_pem_public_key(public_key_str.encode(), backend=default_backend())

		# Decode the signature from base64
		signature_bytes = base64.b64decode(signature)

		# Convert payload to bytes
		payload_bytes = payload.encode("utf-8")

		# Verify the signature using SHA256withRSA
		public_key.verify(signature_bytes, payload_bytes, padding.PKCS1v15(), hashes.SHA256())

		return True

	except InvalidSignature:
		frappe.log_error("Invalid signature", "KCB Signature Verification")
		return False
	except Exception as e:
		frappe.log_error(f"Signature verification error: {e!s}", "KCB Signature Verification")
		return False


def generate_response(message_id, originator_conversation_id, status_code, status_message, transaction_id):
	response = {
		"header": {
			"messageID": message_id,
			"originatorConversationID": originator_conversation_id,
			"statusCode": status_code,
			"statusMessage": status_message,
		},
		"responsePayload": {"transactionInfo": {"transactionId": transaction_id}},
	}

	return response


def process_payment(payment_doc):
	# work on processing payment later
	# change status to processed after linking sales invoice and creating payment entry
	return True

	bill_reference = payment_doc.bill_reference

	if frappe.db.exists("Sales Invoice", {"name": bill_reference}):
		invoice = frappe.get_doc("Sales Invoice", bill_reference)

		payment_entry = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"posting_date": frappe.utils.nowdate(),
				"party_type": "Customer",
				"party": invoice.customer,
				"paid_amount": frappe.utils.flt(payment_doc.amount, 2),
				"received_amount": frappe.utils.flt(payment_doc.amount, 2),
				"paid_to": frappe.db.get_value("Company", invoice.company, "default_cash_account"),
				"paid_from": frappe.db.get_value("Customer", invoice.customer, "default_receivable_account"),
				"reference_no": payment_doc.kcb_transaction_id,
				"reference_date": frappe.utils.nowdate(),
				"company": invoice.company,
				"remarks": f"KCB Till Payment - {payment_doc.narration}",
			}
		)

		payment_entry.append(
			"references",
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": invoice.name,
				"allocated_amount": payment_doc.amount,
			},
		)

		payment_entry.insert(ignore_permissions=True)
		payment_entry.submit()

		payment_doc.payment_entry = payment_entry.name
		payment_doc.sales_invoice = invoice.name

	else:
		frappe.log_error(
			f"No matching invoice found for bill reference: {bill_reference}",
			"KCB Payment Processing",
		)
		raise Exception(f"No matching invoice found for reference: {bill_reference}")


@frappe.whitelist()
def fetch_kcb_payment_transactions(
	phone_number=None, name=None, amount=None, originator_conversation_id=None
):
	filters = {
		"status": "Received",
	}

	if phone_number:
		filters["mobile_number"] = ["like", f"%{phone_number}%"]
	if amount:
		filters["amount"] = amount
	if originator_conversation_id:
		filters["originator_conversation_id"] = ["like", f"%{originator_conversation_id}%"]

	or_filters = []
	if name:
		or_filters = [
			["first_name", "like", f"%{name}%"],
			["middle_name", "like", f"%{name}%"],
			["last_name", "like", f"%{name}%"],
		]

	transactions = frappe.get_all(
		"KCB Payment Transaction",
		filters=filters,
		or_filters=or_filters if or_filters else None,
		pluck="name",
		order_by="creation desc",
	)

	return transactions
