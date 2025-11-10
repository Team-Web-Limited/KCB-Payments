# Copyright (c) 2025, Team Web Africa and contributors
# For license information, please see license.txt

import frappe
import requests
from frappe.model.document import Document
from frappe.utils import add_to_date
from frappe.utils.password import get_decrypted_password
from requests.auth import HTTPBasicAuth


class KCBMpesaSettings(Document):
	def get_credentials(self) -> tuple[str | None, str | None]:
		username = self.username
		password = None

		try:
			password = get_decrypted_password("KCB Mpesa Settings", self.name, "password")
		except frappe.DoesNotExistError:
			frappe.log_error(
				title="KCB Mpesa Settings Not Found",
				message=f"Could not find KCB Mpesa Settings document: {self.name}",
			)
		except Exception as e:
			frappe.log_error(
				title="Failed to Get KCB Mpesa Password",
				message=f"Error retrieving password for {self.name}: {e!s}",
			)

		return username, password

	def token_expired(self) -> bool:
		if not self.access_token or not self.token_expiry:
			return True

		try:
			from frappe.utils import get_datetime

			expiry_time = get_datetime(self.token_expiry).timestamp()
			buffer_time = expiry_time - 5

			return frappe.utils.now() >= buffer_time
		except (AttributeError, TypeError, ValueError) as e:
			frappe.log_error(
				title="Token Expiry Check Failed",
				message=f"Error checking token expiry for {self.name}: {e!s}",
			)
			return True

	def get_access_token(self) -> str | None:
		if not self.token_expired():
			try:
				return get_decrypted_password("KCB Mpesa Settings", self.name, "access_token")
			except Exception:
				# Token field exists, decryption failed, fetch new token
				pass

		consumer_key, consumer_secret = self.get_credentials()

		if not consumer_key or not consumer_secret:
			frappe.throw("KCB Mpesa credentials not found. Please check your settings.")
			return None

		url = "https://uat.buni.kcbgroup.com/token?grant_type=client_credentials" if self.sandbox else ""

		try:
			response = requests.post(url, auth=HTTPBasicAuth(consumer_key, consumer_secret))
			if response.status_code >= 200 and response.status_code < 300:
				token_data = response.json()
				self.access_token = token_data.get("access_token")
				self.expires_in = token_data.get("expires_in")

				self.token_expiry = add_to_date(frappe.utils.now(), seconds=self.expires_in)

				self.save(ignore_permissions=True)
				frappe.db.commit()
				return token_data.get("access_token")
			else:
				frappe.log_error(
					title="Refresh token failed",
					message=f"Could not refresh token. Response:\n{response.text}",
				)
				return None
		except requests.exceptions.RequestException as e:
			frappe.log_error(
				title="Refresh token failed",
				message=f"A network or request-related error occurred:\n{e!s}",
			)
			return None
		except Exception as e:
			frappe.log_error(title="Refresh token failed", message=f"An unexpected error occurred:\n{e!s}")
			return None
