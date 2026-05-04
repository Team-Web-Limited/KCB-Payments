import frappe
import requests
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, get_datetime
from frappe.utils.password import get_decrypted_password
from requests.auth import HTTPBasicAuth

from ...utils.utils import create_payment_gateway, create_payment_gateway_account, sanitize_mobile_number


NCBA_STK_GATEWAY = "NCBA STK Push"


class NCBAPaybillSettings(Document):
	def stk_token_expired(self):
		if not self.stk_access_token or not self.stk_token_expiry:
			return True
		expiry = get_datetime(self.stk_token_expiry)
		buffer = add_to_date(expiry, seconds=-30)
		return get_datetime(frappe.utils.now()) >= buffer

	def get_stk_access_token(self):
		if not self.stk_token_expired():
			return get_decrypted_password("NCBA Paybill Settings", self.name, "stk_access_token")

		url = f"{self.stk_base_url}/payments/api/v1/auth/token"
		username = self.stk_api_username
		password = get_decrypted_password("NCBA Paybill Settings", self.name, "stk_api_password")

		if not username or not password:
			frappe.throw(_("NCBA STK API credentials are not configured."))

		try:
			response = requests.get(url, auth=HTTPBasicAuth(username, password), timeout=15)
		except requests.exceptions.RequestException as e:
			frappe.log_error(title="NCBA STK Token Error", message=str(e))
			return None

		if response.status_code == 200:
			data = response.json()
			self.stk_access_token = data.get("access_token")
			self.stk_expires_in = data.get("expires_in", 18000)
			self.stk_token_expiry = add_to_date(frappe.utils.now(), seconds=self.stk_expires_in)
			self.save(ignore_permissions=True)
			frappe.db.commit()
			return data.get("access_token")

		frappe.log_error(
			title="NCBA STK Token Error",
			message=f"Status: {response.status_code}, Response: {response.text}",
		)
		return None

	def request_for_payment(self, **kwargs):
		args = frappe._dict(kwargs)
		phone_number = args.get("phone_number") or args.get("sender", "")
		if not phone_number:
			frappe.throw(_("A valid phone number is required for NCBA STK payment."))
		phone_number = sanitize_mobile_number(phone_number)

		stk_request = frappe.new_doc("NCBA STK Request")
		stk_request.update({
			"amount": args.get("request_amount", 0.0),
			"phone_number": phone_number,
			"timestamp": frappe.utils.now(),
			"paybill_no": self.stk_paybill_no or self.paybill_number,
			"account_no": _get_ncba_account_no(self.stk_account_no, args.get("reference_docname")),
			"reference_doctype": args.get("reference_doctype"),
			"reference_name": args.get("reference_docname"),
		})
		stk_request.insert(ignore_permissions=True)
		stk_request.submit()

	def on_update(self):
		if not self.stk_enabled:
			return

		create_payment_gateway(
			NCBA_STK_GATEWAY,
			settings="NCBA Paybill Settings",
			controller="NCBA Paybill Settings",
		)

		create_payment_gateway_account(
			gateway=NCBA_STK_GATEWAY,
			payment_channel="Phone",
			company=self.company,
		)

		frappe.db.commit()

		_create_mode_of_payment(NCBA_STK_GATEWAY, company=self.company)


def _get_ncba_account_no(account_no, reference_name):
	if account_no and reference_name:
		return f"{account_no}#{reference_name}"
	return account_no or reference_name or ""


def _create_mode_of_payment(gateway, company=None):
	from erpnext import get_default_company

	payment_gateway_account = frappe.db.get_value(
		"Payment Gateway Account", {"payment_gateway": gateway}, "payment_account"
	)

	if frappe.db.exists("Mode of Payment", gateway):
		return frappe.get_doc("Mode of Payment", gateway)

	if not payment_gateway_account:
		return None

	mode_of_payment = frappe.get_doc({
		"doctype": "Mode of Payment",
		"mode_of_payment": gateway,
		"enabled": 1,
		"type": "Phone",
		"accounts": [{
			"doctype": "Mode of Payment Account",
			"company": company or get_default_company(),
			"default_account": payment_gateway_account,
		}],
	})
	mode_of_payment.insert(ignore_permissions=True)
	return mode_of_payment
