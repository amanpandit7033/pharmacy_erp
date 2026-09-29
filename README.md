# Azmed - Multi-Tenant Pharmacy ERP & POS Billing System

A modern, production-ready multi-tenant Pharmacy Enterprise Resource Planning (ERP) and Point of Sale (POS) system built with Django and Tailwind CSS. Tailored for independent retail pharmacies and multi-store pharmacy chains.

---

## 🌟 Key Features

### 1. Multi-Tenant Architecture & Role-Based Access Control
- **Super Administrator (Platform Owner)**: Full multi-store management, tenant provisioning, global drug catalog administration, platform settings, white-label branding, and platform-wide growth/P&L league tables.
- **Store Administrator (Pharmacy Manager)**: Store operations, inventory and batch management, stock valuation, staff cashier provisioning, store settings, and store-level P&L analytics.
- **Staff (Cashier / Pharmacist)**: Counter POS billing, rapid receipt printing, customer walk-in handling, and shift performance tracking.
- **Role Impersonation**: Super Admin can securely log in as any store admin for immediate customer support.

### 2. Rapid Point of Sale (POS) Billing
- Real-time search across 254k+ drug names, generic salts, and batch numbers.
- Automated **FEFO (First-Expired, First-Out)** batch suggestions.
- Support for custom / manual items without pre-existing catalog entries.
- Automated GST / tax calculations and discount adjustments.
- Instant checkout with Walk-in customer management and prescribing doctor records.

### 3. Dual Printing Engine (Thermal & A4)
- **Thermal Receipt (ESC/POS)**: Formatted for 80mm and 58mm thermal roll printers with clean monospace alignment.
- **A4 Tax Invoice**: Professional letterhead tax invoice featuring store logo, drug license number (DL), GSTIN, itemized batch numbers, and expiry dates.

### 4. Smart Inventory & Expiry Watchlist
- **254,000+ Medicine Master Catalog** with CSV bulk import and autocomplete search.
- **Expiry Watchlist**: 30-day, 60-day, and 90-day risk alerts.
- **Quarantine Workflow**: Automatic and manual quarantine of expired batches to protect customer safety and prevent illegal dispensing.

### 5. Financial & Profit & Loss (P&L) Analytics
- Real-time tracking of:
  - **Gross Revenue (Sales)**
  - **COGS (Cost of Goods Sold / Wholesale Drug Basis)**
  - **Gross Profit Margin (%)**
  - **Inventory Write-offs (Disposed / Expired Stock Loss)**
  - **Net Store Profit**
- Interactive date range calendar picker (Today, Last 7 Days, This Month, Last Month, Custom Range).
- Store growth comparisons and benchmark league tables.

### 6. Localization
- **Timezone**: Indian Standard Time (`Asia/Kolkata`, IST, UTC+05:30).
- **Currency**: Indian Rupee (`₹`) default with multi-currency support per store tenant.

---

## 🛠️ Technology Stack

- **Backend**: Python 3.12, Django 6.1.1
- **Database**: SQLite (Development) / PostgreSQL compatible
- **Frontend**: HTML5, Vanilla JavaScript, Tailwind CSS (CDN), Plus Jakarta Sans
- **Image Processing**: Pillow 12.3.0

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Git

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/pharmacy_erp.git
   cd pharmacy_erp
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Apply database migrations:**
   ```bash
   python manage.py migrate
   ```

5. **Seed demo data (Optional):**
   ```bash
   python manage.py seed_demo_data
   ```

6. **Start the development server:**
   ```bash
   python manage.py runserver
   ```
   Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.

---

## 🧪 Running Automated Tests

Run the complete test suite (103+ unit and integration tests):
```bash
python manage.py test
```

Or run tests by application:
```bash
python manage.py test accounts billing dashboard inventory stores core
```

---

## 🔒 Security & Privacy

- All sensitive credentials and database files (`db.sqlite3`) are excluded from version control.
- Tenant isolation enforced across all views using `TenantAccessMixin` and `RoleRequiredMixin`.

---

## 📄 License
This project is proprietary and confidential.
