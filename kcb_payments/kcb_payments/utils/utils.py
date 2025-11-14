import json
import re
from collections.abc import Generator
from contextlib import contextmanager

import frappe
from frappe import _


def log_and_throw_error(err_msg, context=None):
	frappe.log_error(frappe.get_traceback(), err_msg)
	if context:
		frappe.throw(_(f"{err_msg}: {context}"))


def sanitize_mobile_number(number: str) -> str:
	number = str(number).strip().replace(" ", "").replace("-", "")

	# Normalize country code
	if number.startswith("+254"):
		number = number[4:]
	elif number.startswith("254"):
		number = number[3:]
	elif number.startswith("0"):
		number = number[1:]

	# Validate length and numeric content
	if not re.fullmatch(r"[17]\d{8}", number):
		frappe.throw("Please enter a valid Kenyan mobile number (e.g. 0712345678 or +254712345678).")

	return "254" + number


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


@frappe.whitelist(allow_guest=True, methods=["POST"])
def stk_push_callback():
	frappe.set_user("Administrator")
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
		# TODO: remove this later
		# frappe.log_error(title="STK Callback", message=f"{stk_callback!s}")

		if not stk_callback:
			frappe.log_error("KCB STK Callback Error", f"Missing stkCallback: {payload}")
			return {"status": "failed", "reason": "Missing stkCallback in payload"}

		merchant_request_id = stk_callback.get("MerchantRequestID")
		checkout_request_id = stk_callback.get("CheckoutRequestID")

		if not isinstance(checkout_request_id, str):
			log_and_throw_error("Invalid Checkout Request ID")

		result_code = stk_callback.get("ResultCode")
		status = "Completed" if str(result_code) == "0" else "Failed"

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
		settings = frappe.get_doc("KCB Mpesa Settings", doc.kcb_mpesa_settings)

		# Update the document with callback info
		doc.result_code = result_code
		doc.result_desc = result_desc
		doc.callback_received_at = frappe.utils.now()

		# success
		if status == "Completed" and doc.status != "Completed":
			metadata = stk_callback.get("CallbackMetadata", {}).get("Item", [])
			metadata_dict = {item.get("Name"): item.get("Value") for item in metadata if "Name" in item}

			handle_successful_transaction(doc, metadata_dict, settings, checkout_request_id)

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
