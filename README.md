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
