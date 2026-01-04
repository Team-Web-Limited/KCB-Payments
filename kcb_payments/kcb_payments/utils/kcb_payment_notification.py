import base64
import json
from datetime import datetime

import frappe
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from erpnext.accounts.party import get_party_account
from erpnext.accounts.utils import get_account_currency
from frappe import _


def kcb_auth_handler():
	if (
		frappe.request.path
		== "/api/method/kcb_payments.kcb_payments.utils.kcb_payment_notification.kcb_payment_notification"
	):
		auth_header = frappe.get_request_header("Authorization")

		if auth_header and auth_header.startswith("Bearer "):
			frappe.set_user("Administrator")
			frappe.local.login_manager.user = "Administrator"
			return

	return None


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

        enable_signature_verification = frappe.conf.get("kcb_enable_signature_verification", True)

        if enable_signature_verification:
            signature = frappe.get_request_header("signature")

            if signature:
                signature = signature.strip()

            if not signature:
                frappe.log_error("KCB IPN: Missing signature header", "KCB Payment Notification")
                return generate_response(
                    message_id=data.get("header", {}).get("messageID", "unknown"),
                    originator_conversation_id=data.get("header", {}).get("originatorConversationID", ""),
                    status_code="1",
                    status_message="Missing signature header",
                    transaction_id="",
                )

            raw_payload = frappe.request.data

            if isinstance(raw_payload, bytes):
                raw_payload = raw_payload.decode("utf-8")

            if not verify_signature(raw_payload, signature):
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

        header = data.get("header", {})
        message_id = header.get("messageID")
        originator_conversation_id = header.get("originatorConversationID", "")
        channel_code = header.get("channelCode")
        timestamp = header.get("timeStamp")

        request_payload = data.get("requestPayload", {})
        notification_data = request_payload.get("additionalData", {}).get("notificationData", {})

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

        # Check if this transaction matches a completed STK request (POS payment)
        # originator_conversation_id from IPN matches mpesa_receipt_number from STK request
        is_stk_reconciled = False
        if originator_conversation_id:
            is_stk_reconciled = check_stk_request_match(originator_conversation_id, bill_reference)

        # Determine reconciliation status
        # Reconciled if: matches STK request OR bill_reference contains Payment Request
        should_reconcile = is_stk_reconciled or "#ACC-PRQ-" in bill_reference
        
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
                "reconciled": frappe.utils.flt(amount, 2) if should_reconcile else 0,
                "transaction_date": transaction_date,
                "kcb_transaction_id": kcb_transaction_id,
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,
                "currency": currency,
                "narration": narration,
                "transaction_type": transaction_type,
                "balance": frappe.utils.flt(balance, 2) if balance else 0.0,
                "status": "Reconciled" if should_reconcile else "Unreconciled",
            }
        )

        payment_doc.insert(ignore_permissions=True)
        payment_doc.submit()
        frappe.db.commit()

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

def check_stk_request_match(mpesa_receipt_number, bill_reference):
    """
    Check if this IPN transaction matches a completed STK request.
    
    Args:
        mpesa_receipt_number: The originator_conversation_id from IPN (matches mpesa_receipt_number in STK)
        bill_reference: The bill_reference from IPN in format "till_no#invoice_no" (e.g., "7504343#ACC-SINV-2026-00780")
    
    Returns:
        bool: True if matches a completed STK request, False otherwise
    """
    try:
        # Find STK request with matching mpesa_receipt_number and status = Completed
        stk_request = frappe.db.get_value(
            "KCB Mpesa STK Request",
            {
                "mpesa_receipt_number": mpesa_receipt_number,
                "status": "Completed"
            },
            ["name", "reference_name"],
            as_dict=True
        )
        
        if not stk_request:
            return False
        
        # Extract invoice number from bill_reference (after the #)
        # Format: "7504343#ACC-SINV-2026-00780"
        if "#" in bill_reference:
            invoice_from_ipn = bill_reference.split("#", 1)[1]
        else:
            invoice_from_ipn = bill_reference
        
        # Compare invoice numbers
        if invoice_from_ipn == stk_request.reference_name:
            frappe.logger().info(
                f"STK Request match found: IPN transaction {mpesa_receipt_number} "
                f"matches STK request {stk_request.name} for invoice {invoice_from_ipn}"
            )
            return True
        
        return False
        
    except Exception as e:
        frappe.log_error(
            "STK Request Match Check Error",
            f"Error checking STK request match: {str(e)}\n"
            f"mpesa_receipt_number: {mpesa_receipt_number}\n"
            f"bill_reference: {bill_reference}\n"
            f"Traceback: {frappe.get_traceback()}"
        )
        return False


def verify_signature(payload, signature):
	try:
		public_key_str = frappe.conf.get("kcb_public_key") or frappe.db.get_single_value(
			"KCB IPN Settings", "public_key"
		)

		if not public_key_str:
			frappe.log_error("KCB public key not configured", "KCB Signature Verification")
			return False

		public_key = serialization.load_pem_public_key(public_key_str.encode(), backend=default_backend())

		signature_bytes = base64.b64decode(signature)

		payload = json.dumps(json.loads(payload), separators=(",", ":"))

		try:
			payload_bytes = payload.encode("utf-8")
			public_key.verify(signature_bytes, payload_bytes, padding.PKCS1v15(), hashes.SHA256())
			return True
		except InvalidSignature:
			frappe.log_error(
				"KCB Signature Verification Failed",
				f"Payload (first 500 chars): {payload[:500]}\n"
				f"Signature (first 100 chars): {signature[:100]}\n",
			)
	except Exception as e:
		frappe.log_error(
			"KCB Signature Verification Error",
			f"Signature verification error: {e!s}\n"
			f"Error type: {type(e).__name__}\n"
			f"Payload length: {len(payload) if payload else 0}\n"
			f"Signature provided: {bool(signature)}\n"
			f"Traceback: {frappe.get_traceback()}",
		)
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


@frappe.whitelist()
def process_kcb_payment(payment, sales_invoice):
	try:
		payment_doc = frappe.get_doc("KCB Payment Transaction", payment)
		sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice)
	except Exception as e:
		frappe.log_error("KCB Payment Processing", f"Error fetching documents: {e!s}")
		frappe.throw(_("Invalid payment or sales invoice document."))

	if payment_doc.status == "Reconciled":
		frappe.throw(_("Payment has already been reconciled."))

	if sales_invoice_doc.outstanding_amount <= 0:
		frappe.throw(_("Sales Invoice is already fully paid."))

	try:
		party_account = get_party_account(
			party_type="Customer",
			party=sales_invoice_doc.customer,
			company=sales_invoice_doc.company,
		)

		if not party_account:
			frappe.throw(
				_(
					f"Could not find party account for customer {sales_invoice_doc.customer} in company {sales_invoice_doc.company}"
				)
			)

		party_account_currency = get_account_currency(party_account)

		if party_account_currency != payment_doc.currency:
			frappe.throw(
				_(
					f"Currency mismatch between payment {payment_doc.currency} and party account {party_account_currency}"
				)
			)

		paid_to_account = frappe.db.get_value(
			"Mode of Payment Account",
			{"parent": "KCB", "company": sales_invoice_doc.company},
			"default_account",
		)

		if not paid_to_account:
			frappe.throw(
				_("KCB payment account not configured for company {0}").format(sales_invoice_doc.company)
			)

		reconcilable_amount = payment_doc.amount - payment_doc.reconciled

		if reconcilable_amount <= 0:
			frappe.throw("Payment has been used up, cannot be used for further reconciliation")
			return

		allocated_amount = min(reconcilable_amount, sales_invoice_doc.outstanding_amount)

		payment_entry = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"company": sales_invoice_doc.company,
				"posting_date": frappe.utils.nowdate(),
				"mode_of_payment": "KCB",
				"payment_type": "Receive",
				"party_type": "Customer",
				"party": sales_invoice_doc.customer,
				"paid_from": sales_invoice_doc.debit_to,
				"paid_to": paid_to_account,
				"paid_amount": payment_doc.amount,
				"received_amount": payment_doc.amount,
				"reference_no": payment_doc.kcb_transaction_id,
				"reference_date": str(payment_doc.modified).split(" ")[0],
				"references": [
					{
						"reference_doctype": "Sales Invoice",
						"reference_name": sales_invoice_doc.name,
						"due_date": sales_invoice_doc.due_date,
						"outstanding_amount": sales_invoice_doc.outstanding_amount,
						"allocated_amount": allocated_amount,
					}
				],
			}
		)

		payment_entry.insert(ignore_permissions=True)
		payment_entry.submit()

		payment_doc.reconciled += allocated_amount
		payment_doc.status = (
			"Reconciled" if payment_doc.amount <= payment_doc.reconciled else "Partly Reconciled"
		)
		payment_doc.save(ignore_permissions=True)
		frappe.db.commit()

		return {
			"success": True,
			"payment_entry": payment_entry.name,
			"message": f"Payment Entry {payment_entry.name} created successfully for Sales Invoice {sales_invoice_doc.name}.",
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("KCB Payment Processing", f"Error processing payment: {e!s}")
		frappe.throw(_("Failed to process payment: {0}").format(str(e)))


@frappe.whitelist()
def fetch_kcb_payment_transactions(
	phone_number=None, name=None, amount=None, originator_conversation_id=None
):
	filters = {
		"status": ["in", ["Partly Reconciled", "Unreconciled"]],
	}

	if phone_number:
		filters["mobile_number"] = ["like", f"%{phone_number}%"]
	if amount:
		filters["amount"] = amount
	if originator_conversation_id:
		filters["originator_conversation_id"] = [
			"like",
			f"%{originator_conversation_id}%",
		]

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
		fields=[
			"name",
			"mobile_number",
			"first_name",
			"last_name",
			"(amount - reconciled) as amount",
			"originator_conversation_id",
		],
		order_by="creation desc",
	)

	return transactions
