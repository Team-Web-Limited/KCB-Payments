# Copyright (c) 2025, Team Web Africa and contributors
# For license information, please see license.txt

import re
import time
import uuid

import frappe
import requests
from frappe.model.document import Document

from ..kcb_mpesa_settings.kcb_mpesa_settings import KCBMpesaSettings


class KCBMpesaSTKRequest(Document):
	def sanitize_mobile_number(self, number: str) -> str:
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

	def generate_stk_push(self):
		self.settings = frappe.get_doc("KCB Mpesa Settings", self.kcb_mpesa_settings)
		access_token = self.settings.get_access_token()

		if not access_token:
			frappe.throw("Failed to retrieve access token. Please check KCB Mpesa Settings.")

		url = url = "https://uat.buni.kcbgroup.com/mm/api/request/1.0.0/stkpush" if self.sandbox else ""

		phone_number = self.sanitize_mobile_number(self.phone_number)
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
			"phoneNumber": phone_number,
			"amount": int(self.amount),
			"invoiceNumber": f"{self.till_no}-{frappe.utils.random_string(6)}",
			"sharedShortCode": True,
			"orgShortCode": "",
			"orgPassKey": "",
			"callbackUrl": "https://posthere.io/f613-4b7f-b82b",
			"transactionDescription": self.transaction_desc,
		}

		frappe.logger().info(
			{
				"event": "KCB STK Push Initiated",
				"timestamp": frappe.utils.now(),
				"message_id": message_id,
				"url": url,
				"phone_number": phone_number,
				"payload": payload,
				"headers": {k: v for k, v in headers.items() if k != "Authorization"},
			}
		)

		try:
			response = requests.post(url, headers=headers, json=payload, timeout=10)
			response_text = response.text
			response_json = {}

			try:
				response_json = response.json()
			except ValueError:
				frappe.log_error("Invalid JSON in KCB STK Push response", response_text)
				return {"status_code": response.status_code, "error": "Invalid JSON response from KCB API"}

			if response.status_code in [200, 201]:
				if "response" in response_json and response_json["response"].get("ResponseCode") == "0":
					response_data = response_json["response"]

					response_data = response.json().get("response", {})
					self.merchant_request_id = response_data.get("MerchantRequestID", "")
					self.response_code = response_data.get("ResponseCode", "")
					self.customer_message = response_data.get("CustomerMessage", "")
					self.checkout_request_id = response_data.get("CheckoutRequestID", "")
					self.response_description = response_data.get("ResponseDescription", "")

					self.save(ignore_permissions=True)
					frappe.db.commit()
					return {"status_code": response.status_code, "response": response_json}
				else:
					# Business-level error even with HTTP 200
					frappe.log_error(
						title="KCB STK Push Business Error", message=f"Response: {response_json}"
					)
					return {
						"status_code": response.status_code,
						"error": response_json.get("response", response_json),
					}
			else:
				# Non-2xx HTTP error
				frappe.log_error(
					title="KCB STK Push HTTP Error",
					message=f"Status: {response.status_code}, Response: {response_text}",
				)
				return {"status_code": response.status_code, "error": response_json}
		except requests.exceptions.RequestException as e:
			frappe.log_error(title="KCB Mpesa STK Push Failed", message=f"Request failed: {e!s}")
			return {"status_code": 500, "error": str(e)}
		except Exception as e:
			frappe.log_error(title="KCB Mpesa STK Push Failed", message=f"Unexpected error: {e!s}")
			return {"status_code": 500, "error": str(e)}
