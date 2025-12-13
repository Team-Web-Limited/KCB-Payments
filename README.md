### KCB Payments

KCB Payments is a custom [frappe](https://frappe.io/framework) application that integrates with [KCB's BUNI API](https://buni.kcbgroup.com/). It is built to extend [ERPNext](https://frappe.io/erpnext/ke), enabling seamless mobile payments from customers bo businesses via Mpesa's _Mpesa Express API Service_

### Requirements

1. [ERPNext](https://github.com/frappe/erpnext)
2. [Payments](https://github.com/frappe/payments)

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app kcb_payments
```

### Doctypes
#### 1) KCB MPesa Settings
Create this for each till/paybill through which we want to receive payments
<img width="2709" height="1465" alt="image" src="https://github.com/user-attachments/assets/6c5d2546-f48d-49a4-93e3-c242e1f860b8" />

#### 2) KCB Mpesa STK Request
This will be created for each STK Push generated from the system

<p align="center">
  <img width="2678" height="772" alt="image" src="https://github.com/user-attachments/assets/6920b75a-c364-4ab3-b977-8e758e8ef276" />
  <br>
  <em>Successful STK request</em>
</p>

<p align="center">
  <img width="2685" height="1151" alt="image" src="https://github.com/user-attachments/assets/300a6b9c-ae7e-4a73-95b5-419e30f8f735" />
  <br>
  <em>Failed STK request</em>
</p>

#### 3) KCB IPN Settings
This document stores the public key that is used to verify payment notifications from KCB.
<img width="1904" height="942" alt="image" src="https://github.com/user-attachments/assets/c626e825-b738-49dd-80f3-fa7b8f11bf41" />

#### 4) KCB Payment Transaction
All KCB Payments (made either by stk push, or customer initiated payments), made to a certain paybill/till number will be recorded here.<br/>
This document is system generated, user cannot create a new record for _KCB Payment Transaction_
<img width="2680" height="1406" alt="image" src="https://github.com/user-attachments/assets/13fe1cdc-a5ec-427a-8f74-9f8bb0ef52c7" />

### Usage

#### a) STK Push

##### 1) Create a payment request from a submitted sales invoice/sales order
<img width="2732" height="1095" alt="image" src="https://github.com/user-attachments/assets/66b1c757-a6ef-41c9-a5e5-8d060e223f98" />

##### 2) Confirm payment request details and submit
<p align="center">
  <img width="2400" height="892" alt="image" src="https://github.com/user-attachments/assets/45b9d9f3-a597-49e5-8269-3e9001dc1cdf" />
  <br>
  <em>Confirm payment request details</em>
</p>

<p align="center">
  <img width="2885" height="687" alt="image" src="https://github.com/user-attachments/assets/db85ad11-13a7-46c0-ad7e-c522d90c896d" />
  <br>
  <em>Submit payment request</em>
</p>

<p align="center">
  <img width="2760" height="1098" alt="image" src="https://github.com/user-attachments/assets/d9a3b57d-a812-4811-b783-e580fec36d8c" />
  <br>
  <em>A sumbmitted payment request has the status <b>Requested</b></em>
</p>

<p align="center">
  <img width="214" height="999" alt="image" src="https://github.com/user-attachments/assets/a8885ae3-972d-41a5-9c95-5349e9e6494b" />
  <br>
  <em>Customer enters pin to confirm payment</em>
</p>

<p align="center">
  <img width="2653" height="633" alt="image" src="https://github.com/user-attachments/assets/51923dc4-636b-45ca-b1bc-b462407b980f" />
  <br>
  <em>Completed payment request</em>
</p>

#### b) Paybill/Till Reconciliation
<p align="center">
  <img width="2639" height="884" alt="image" src="https://github.com/user-attachments/assets/29b5e52a-80b0-4812-8fa9-516dc7dc2e90" />
  <br>
  <em>Click Get KCB Payments on a submitted invoice with an outstanding amount</em>
</p>

<p align="center">
  <img width="2602" height="1343" alt="image" src="https://github.com/user-attachments/assets/effdae8c-d5b9-4eee-ad17-f4108957046d" />
  <br>
  <em>Search for payments using any of the criteria in the dialog box that appears</em>
</p>

<p align="center">
  <img width="1646" height="483" alt="image" src="https://github.com/user-attachments/assets/ef87672e-942a-4571-b339-d78854170076" />
  <br>
  <em>CLick Reconcile, for any of the fetched payments.</em>
</p>

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/kcb_payments
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
