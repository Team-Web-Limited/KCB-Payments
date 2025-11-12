import json
from collections.abc import Generator
from contextlib import contextmanager

import frappe
from frappe import _


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


def create_payment_gateway(gateway: str, settings: str | None = None, controller: str | None = None) -> None:
	if not frappe.db.exists("Payment Gateway", gateway):
		payment_gateway = frappe.get_doc(
			{
				"doctype": "Payment Gateway",
				"gateway": gateway,
				"gateway_settings": settings,
				"gateway_controller": controller,
			}
		)
		payment_gateway.insert(ignore_permissions=True)


def create_payment_gateway_account(gateway, payment_channel="Email", company=None):
	from erpnext.setup.setup_wizard.operations.install_fixtures import (
		create_bank_account,
	)

	company = company or frappe.get_cached_value("Global Defaults", "Global Defaults", "default_company")
	if not company:
		return

	# NOTE: we translate Payment Gateway account name because that is going to be used by the end user
	bank_account = frappe.db.get_value(
		"Account",
		{"account_name": _(gateway), "company": company},
		["name", "account_currency"],
		as_dict=1,
	)

	if not bank_account:
		# check for untranslated one
		bank_account = frappe.db.get_value(
			"Account",
			{"account_name": gateway, "company": company},
			["name", "account_currency"],
			as_dict=1,
		)

	if not bank_account:
		# try creating one
		bank_account = create_bank_account({"company_name": company, "bank_account": _(gateway)})

	if not bank_account:
		frappe.msgprint(_("Payment Gateway Account not created, please create one manually."))
		return

	# if payment gateway account exists, return
	if frappe.db.exists(
		"Payment Gateway Account",
		{"payment_gateway": gateway, "currency": bank_account.account_currency},
	):
		return

	try:
		frappe.get_doc(
			{
				"doctype": "Payment Gateway Account",
				"is_default": 1,
				"payment_gateway": gateway,
				"payment_account": bank_account.name,
				"currency": bank_account.account_currency,
				"payment_channel": payment_channel,
			}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)

	except frappe.DuplicateEntryError:
		# already exists, due to a reinstall?
		pass


@contextmanager
def erpnext_app_import_guard() -> Generator:
	marketplace_link = '<a href="https://frappecloud.com/marketplace/apps/erpnext">Marketplace</a>'
	github_link = '<a href="https://github.com/frappe/erpnext">GitHub</a>'
	msg = _("erpnext app is not installed. Please install it from {} or {}").format(
		marketplace_link, github_link
	)
	try:
		yield
	except ImportError:
		frappe.throw(msg, title=_("Missing ERPNext App"))
