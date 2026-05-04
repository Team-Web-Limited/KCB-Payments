import frappe
import requests
from frappe import _


def generate_ncba_stk_push(stk_request, settings):
	"""Initiate an NCBA STK push transaction and update the request doc."""
	access_token = settings.get_stk_access_token()
	if not access_token:
		stk_request.status = "Failed"
		stk_request.error_message = "Failed to retrieve NCBA access token"
		stk_request.save(ignore_permissions=True)
		frappe.db.commit()
		return

	url = f"{settings.stk_base_url}/payments/api/v1/stk-push/initiate"

	headers = {
		"Content-Type": "application/json",
		"Authorization": f"Bearer {access_token}",
	}

	payload = {
		"TelephoneNo": stk_request.phone_number,
		"Amount": str(round(float(stk_request.amount))),
		"PayBillNo": stk_request.paybill_no or settings.stk_paybill_no or settings.paybill_number,
		"AccountNo": stk_request.account_no or settings.stk_account_no or "",
		"Network": "Safaricom",
		"TransactionType": "CustomerPayBillOnline",
	}

	response = requests.post(url, headers=headers, json=payload, timeout=30)
	response_json = response.json()

	stk_request.transaction_id = response_json.get("TransactionID")
	stk_request.status_code = response_json.get("StatusCode")
	stk_request.status_description = response_json.get("StatusDescription")
	stk_request.reference_id = response_json.get("ReferenceID")

	if response_json.get("TransactionID"):
		stk_request.status = "In Progress"
	else:
		stk_request.status = "Failed"
		stk_request.error_message = response_json.get("StatusDescription", response.text)
		frappe.log_error(
			title="NCBA STK Push Failed",
			message=f"Status: {response.status_code}, Response: {response.text}",
		)

	stk_request.save(ignore_permissions=True)
	frappe.db.commit()


def query_ncba_stk_status(stk_request):
	"""Query NCBA for the status of an STK push transaction."""
	if stk_request.status == "Completed":
		return

	if not stk_request.transaction_id:
		return

	settings = frappe.get_single("NCBA Paybill Settings")
	try:
		access_token = settings.get_stk_access_token()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "NCBA STK Query Token Error")
		return
	if not access_token:
		frappe.log_error("NCBA STK Query", "Failed to get access token for STK query")
		return

	url = f"{settings.stk_base_url}/payments/api/v1/stk-push/query"

	headers = {
		"Content-Type": "application/json",
		"Authorization": f"Bearer {access_token}",
	}

	payload = {"TransactionID": stk_request.transaction_id}

	try:
		response = requests.post(url, headers=headers, json=payload, timeout=60)
	except requests.exceptions.Timeout:
		# Transient: keep In Progress so the next poll retries
		stk_request.query_checked_at = frappe.utils.now()
		stk_request.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.log_error(
			title="NCBA STK Query Timeout",
			message=f"Timeout querying TransactionID={stk_request.transaction_id}",
		)
		return
	except requests.exceptions.RequestException as e:
		stk_request.query_checked_at = frappe.utils.now()
		stk_request.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.log_error(
			title="NCBA STK Query Connection Error",
			message=f"TransactionID={stk_request.transaction_id} | {e}",
		)
		return

	try:
		result = response.json()
	except ValueError:
		frappe.log_error(
			title="NCBA STK Query Invalid JSON",
			message=f"TransactionID={stk_request.transaction_id} | {response.text}",
		)
		return

	status = (result.get("status") or "").upper()
	description = result.get("description") or ""

	stk_request.query_status = status
	stk_request.query_description = description
	stk_request.query_checked_at = frappe.utils.now()

	# NCBA returns FAILED + "Error occurred while processing query" transiently
	# while the transaction is still being processed. Treat it as pending so
	# polling continues, instead of marking the request permanently Failed.
	transient_error = (
		status == "FAILED"
		and "error occurred while processing query" in description.lower()
	)

	if status == "SUCCESS":
		stk_request.status = "Completed"
	elif status == "FAILED" and not transient_error:
		stk_request.status = "Failed"
		stk_request.error_message = description

	stk_request.save(ignore_permissions=True)
	frappe.db.commit()


def poll_pending_ncba_stk_requests():
	"""Background job: query NCBA for all 'In Progress' STK requests.

	Runs every 2 minutes via scheduler to catch completions that
	the frontend polling may have missed (e.g. browser closed,
	network blip, timeout).
	"""
	settings = frappe.get_single("NCBA Paybill Settings")
	if not settings.stk_enabled:
		return

	# Only check requests created between 30 seconds and 30 minutes ago
	cutoff = frappe.utils.add_to_date(frappe.utils.now(), minutes=-30)
	min_age = frappe.utils.add_to_date(frappe.utils.now(), seconds=-30)

	pending = frappe.get_all(
		"NCBA STK Request",
		filters={
			"status": "In Progress",
			"docstatus": 1,
			"transaction_id": ("is", "set"),
			"creation": ("between", [cutoff, min_age]),
		},
		fields=["name"],
		order_by="creation desc",
		limit_page_length=50,
	)

	if not pending:
		return

	for row in pending:
		try:
			stk_request = frappe.get_doc("NCBA STK Request", row.name)
			query_ncba_stk_status(stk_request)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"NCBA STK Background Poll Error: {row.name}",
			)
