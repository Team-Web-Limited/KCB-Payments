import base64
import hashlib
import hmac
import json
from datetime import datetime

import frappe
from frappe import _


def ncba_auth_handler():
	"""Allow access to the NCBA payment notification endpoint."""
	if (
		frappe.request.path
		== "/api/method/kcb_payments.kcb_payments.utils.ncba_payment_notification.ncba_payment_notification"
	):
		frappe.set_user("Administrator")
		return

	return None


@frappe.whitelist(allow_guest=True, methods=["POST"])
def ncba_payment_notification():
	"""
	Receive and process NCBA Paybill push notifications.

	Parses the flat JSON payload per the NCBA Paybill-Level Push Notifications
	Service Guide and returns {"ResultCode": "0/1", "ResultDesc": "..."}.
	"""
	frappe.set_user("Administrator")

	logger = frappe.logger("ncba_notification", allow_site=True, file_count=50)

	data = None
	try:
		# Reject oversized payloads (NCBA notifications are small JSON)
		raw = frappe.request.data

		# Log raw incoming payload regardless of validation outcome
		try:
			raw_text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw or "")
		except Exception:
			raw_text = "<unreadable>"
		logger.info(f"NCBA IPN received | ip={frappe.local.request_ip} | body={raw_text}")

		if not raw or not raw.strip():
			frappe.log_error("NCBA IPN: Empty request body", "NCBA Payment Notification")
			return _ncba_response("1", "Empty request body")

		if len(raw) > 10_000:
			frappe.log_error("NCBA IPN: Payload too large", "NCBA Payment Notification")
			return _ncba_response("1", "Payload too large")

		try:
			data = json.loads(raw)
		except (json.JSONDecodeError, ValueError):
			frappe.log_error("NCBA IPN: Malformed JSON body", "NCBA Payment Notification")
			return _ncba_response("1", "Invalid request format")

		if not data or not isinstance(data, dict):
			frappe.log_error("NCBA IPN: Empty or non-object body", "NCBA Payment Notification")
			return _ncba_response("1", "Invalid request body")

		# --- Validate credentials against settings ---
		settings = frappe.get_single("NCBA Paybill Settings")
		if not settings.enabled:
			return _ncba_response("1", "Service not enabled")

		received_username = data.get("Username") or ""
		received_password = data.get("Password") or ""

		if (
			not hmac.compare_digest(received_username, settings.username or "")
			or not hmac.compare_digest(received_password, settings.get_password("password") or "")
		):
			frappe.log_error(
				"NCBA IPN: Invalid credentials",
				"NCBA Payment Notification",
			)
			return _ncba_response("1", "Authentication failed")

		# --- Extract fields from flat NCBA JSON ---
		trans_type = data.get("TransType", "")
		trans_id = data.get("TransID", "")
		trans_time = data.get("TransTime", "")
		trans_amount = data.get("TransAmount", "")
		business_short_code = data.get("BusinessShortCode", "")
		bill_ref_number = data.get("BillRefNumber", "")
		narrative = data.get("Narrative", "")
		mobile = data.get("Mobile", "")
		customer_name = data.get("name", "")
		ft_ref = data.get("FTRef", "")
		received_hash = data.get("Hash", "")

		# --- Validate required fields ---
		if not all([trans_id, trans_amount, mobile, business_short_code]):
			frappe.log_error(
				f"NCBA IPN: Missing required fields - TransID={trans_id}, "
				f"TransAmount={trans_amount}, Mobile={mobile}, "
				f"BusinessShortCode={business_short_code}",
				"NCBA Payment Notification",
			)
			return _ncba_response("1", "Missing required fields")

		# --- Verify hash ---
		secret_key = settings.get_password("secret_key")
		expected_hash = _compute_ncba_hash(
			secret_key, trans_type, trans_id, trans_time, trans_amount,
			business_short_code, bill_ref_number, mobile, customer_name,
		)
		if not hmac.compare_digest(received_hash, expected_hash):
			frappe.log_error(
				f"NCBA IPN: Hash mismatch for TransID={trans_id}",
				"NCBA Payment Notification",
			)
			return _ncba_response("1", "Hash verification failed")

		# --- Check for duplicate transactions (idempotency) ---
		if frappe.db.exists("NCBA Payment Transaction", {"trans_id": trans_id}):
			frappe.log_error(
				f"NCBA IPN: Duplicate transaction {trans_id}",
				"NCBA Payment Notification",
			)
			return _ncba_response("0", "Duplicate transaction - already processed")

		# --- Parse transaction date from TransTime (YYYYMMDDhhmmss) ---
		transaction_date = None
		if trans_time and len(trans_time) >= 8:
			try:
				transaction_date = datetime.strptime(trans_time[:8], "%Y%m%d").date()
			except ValueError:
				transaction_date = frappe.utils.nowdate()

		# --- Determine reconciliation status ---
		should_reconcile = bill_ref_number and "#ACC-PRQ-" in bill_ref_number
		amount_val = frappe.utils.flt(trans_amount, 2)

		# --- Create NCBA Payment Transaction ---
		payment_doc = frappe.get_doc({
			"doctype": "NCBA Payment Transaction",
			"trans_id": trans_id,
			"trans_type": trans_type,
			"trans_time": trans_time,
			"ft_ref": ft_ref,
			"amount": amount_val,
			"business_short_code": business_short_code,
			"bill_ref_number": bill_ref_number,
			"narrative": narrative,
			"mobile_number": mobile,
			"customer_name": customer_name,
			"transaction_date": transaction_date,
			"currency": "KES",
			"reconciled": amount_val if should_reconcile else 0,
			"status": "Reconciled" if should_reconcile else "Unreconciled",
		})

		payment_doc.insert(ignore_permissions=True)
		payment_doc.submit()
		frappe.db.commit()

		return _ncba_response("0", "Notification received successfully")

	except frappe.DuplicateEntryError:
		# Race condition: another request already inserted this trans_id
		return _ncba_response("0", "Duplicate transaction - already processed")
	except Exception:
		frappe.log_error(
			"NCBA Payment Notification",
			f"NCBA IPN Error\n{frappe.get_traceback()}",
		)
		return _ncba_response("1", "Processing error")


def _compute_ncba_hash(
	secret_key, trans_type, trans_id, trans_time, trans_amount,
	business_short_code, bill_ref_number, mobile, customer_name,
):
	"""
	Compute the NCBA hash per their spec:
	SHA256(secretKey + TransType + TransID + TransTime + TransAmount +
	       BusinessShortCode + BillRefNumber + Mobile + Name + "1") -> Base64
	"""
	hash_input = (
		str(secret_key)
		+ str(trans_type)
		+ str(trans_id)
		+ str(trans_time)
		+ str(trans_amount)
		+ str(business_short_code)
		+ str(bill_ref_number)
		+ str(mobile)
		+ str(customer_name)
		+ "1"
	)
	sha256_hex = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
	return base64.b64encode(sha256_hex.encode("utf-8")).decode("utf-8")


def _ncba_response(result_code, result_desc):
	"""Return response in the NCBA-expected format."""
	response = {
		"ResultCode": result_code,
		"ResultDesc": result_desc,
	}
	try:
		frappe.logger("ncba_notification", allow_site=True, file_count=50).info(
			f"NCBA IPN response | {response}"
		)
	except Exception:
		pass
	return response
